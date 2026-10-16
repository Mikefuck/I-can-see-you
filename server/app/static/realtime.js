/* One event stream per page; JSON endpoints continue to supply authorized snapshots. */
(() => {
  "use strict";
  class Realtime {
    constructor(url) {
      this.url = url;
      this.source = null;
      this.state = "fallback";
      this.listeners = new Set();
      this.stateListeners = new Set();
      this.areas = new Set();
      this.delivery = this.retry = this.watchdog = 0;
      this.retryDelay = 3000;
      this.started = false;
      this.visibility = () => document.hidden ? this.pause() : this.resume();
      this.hide = () => this.pause();
      this.show = () => { if (!document.hidden) this.resume(); };
    }

    subscribe(listener) { this.listeners.add(listener); }
    onState(listener) { this.stateListeners.add(listener); }
    setState(state) {
      if (this.state === state) return;
      this.state = state;
      this.stateListeners.forEach(listener => listener(state));
    }

    notify(areas) {
      areas.forEach(area => this.areas.add(area));
      if (this.delivery || document.hidden) return;
      this.delivery = setTimeout(() => {
        this.delivery = 0;
        const pending = [...this.areas];
        this.areas.clear();
        this.listeners.forEach(listener => listener(pending));
      }, 150);
    }

    touch() {
      clearTimeout(this.watchdog);
      this.watchdog = setTimeout(() => {
        this.disconnect();
        this.setState("reconnecting");
        this.connect();
      }, 45000);
    }

    connect() {
      if (!this.started || document.hidden || this.source || !window.EventSource) return;
      clearTimeout(this.retry);
      const source = this.source = new EventSource(this.url);
      this.touch();
      source.addEventListener("ready", () => {
        if (source !== this.source) return;
        this.retryDelay = 3000;
        this.touch();
        this.setState("connected");
        this.notify(["access", "live", "history"]);
      });
      source.addEventListener("changed", event => {
        if (source !== this.source) return;
        try {
          const { areas } = JSON.parse(event.data);
          if (!Array.isArray(areas)) return;
          this.touch();
          this.notify(areas.filter(area => ["access", "live", "history", "metadata"].includes(area)));
        } catch (error) { /* Periodic snapshots remain available if a proxy corrupts a frame. */ }
      });
      source.addEventListener("ping", () => { if (source === this.source) this.touch(); });
      source.addEventListener("reset", () => {
        if (source !== this.source) return;
        this.stop();
        location.reload();
      });
      source.onerror = () => {
        if (source !== this.source) return;
        this.setState("reconnecting");
        // Network interruptions use native EventSource reconnection. Terminal HTTP
        // failures also get a bounded retry, including when connected to an old server.
        if (source.readyState === EventSource.CLOSED) {
          this.disconnect();
          this.retry = setTimeout(() => this.connect(), this.retryDelay);
          this.retryDelay = Math.min(30000, this.retryDelay * 2);
        }
      };
    }

    disconnect() {
      clearTimeout(this.retry);
      clearTimeout(this.watchdog);
      this.source?.close();
      this.source = null;
    }
    pause() {
      this.disconnect();
      clearTimeout(this.delivery);
      this.delivery = 0;
      this.setState("paused");
    }
    resume() {
      if (!this.started) return;
      this.notify(["access", "live", "history"]);
      this.connect();
    }
    start() {
      if (this.started) return;
      this.started = true;
      document.addEventListener("visibilitychange", this.visibility);
      window.addEventListener("pagehide", this.hide);
      window.addEventListener("pageshow", this.show);
      this.connect();
    }
    stop() {
      this.started = false;
      this.pause();
      document.removeEventListener("visibilitychange", this.visibility);
      window.removeEventListener("pagehide", this.hide);
      window.removeEventListener("pageshow", this.show);
    }
  }
  window.FocusRealtime = Realtime;
})();
