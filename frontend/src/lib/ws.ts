/** Single multiplexed WebSocket with automatic reconnection and topic re-subscription. */

import { wsUrl } from "./api";

type Handler = (msg: any) => void;

class WsClient {
  private ws: WebSocket | null = null;
  private topics = new Map<string, Set<Handler>>();
  private global = new Set<Handler>();
  private statusHandlers = new Set<(s: WsStatus) => void>();
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  status: WsStatus = { state: "connecting", latencyMs: null, reconnects: 0, lastMessage: 0 };

  connect() {
    if (typeof window === "undefined") return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    this.setStatus({ state: "connecting" });
    const ws = new WebSocket(wsUrl());
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setStatus({ state: "open" });
      for (const t of this.topics.keys()) this.send({ op: "sub", topic: t });
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.send({ op: "ping", ts: Date.now() }), 5000);
    };
    ws.onmessage = (ev) => {
      let msg: any;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      this.status.lastMessage = Date.now();
      if (msg.type === "pong") {
        this.setStatus({ latencyMs: Date.now() - (msg.ts ?? Date.now()) });
        return;
      }
      if (msg.topic && this.topics.has(msg.topic)) {
        for (const h of this.topics.get(msg.topic)!) h(msg);
      }
      if (!msg.topic) for (const h of this.global) h(msg);
    };
    ws.onclose = () => {
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.setStatus({ state: "closed", reconnects: this.status.reconnects + 1 });
      const delay = Math.min(15000, 500 * 2 ** this.retry++);
      this.timer = setTimeout(() => this.connect(), delay);
    };
    ws.onerror = () => ws.close();
  }

  private send(obj: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  subscribe(topic: string, h: Handler): () => void {
    this.connect();
    let set = this.topics.get(topic);
    if (!set) {
      set = new Set();
      this.topics.set(topic, set);
      this.send({ op: "sub", topic });
    }
    set.add(h);
    return () => {
      const s = this.topics.get(topic);
      if (!s) return;
      s.delete(h);
      if (s.size === 0) {
        this.topics.delete(topic);
        this.send({ op: "unsub", topic });
      }
    };
  }

  /** Re-request a full snapshot for a topic (e.g. after settings changes). */
  resync(topic: string) {
    this.send({ op: "sub", topic });
  }

  onGlobal(h: Handler): () => void {
    this.connect();
    this.global.add(h);
    return () => this.global.delete(h);
  }

  onStatus(h: (s: WsStatus) => void): () => void {
    this.statusHandlers.add(h);
    h(this.status);
    return () => this.statusHandlers.delete(h);
  }

  private setStatus(p: Partial<WsStatus>) {
    this.status = { ...this.status, ...p };
    for (const h of this.statusHandlers) h(this.status);
  }

  reconnectNow() {
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.retry = 0;
    this.connect();
  }
}

export interface WsStatus {
  state: "connecting" | "open" | "closed";
  latencyMs: number | null;
  reconnects: number;
  lastMessage: number;
}

export const ws = new WsClient();
