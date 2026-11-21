// Runs an api/*.js Vercel handler as a Cloudflare Pages Function, unchanged.
//
// functions/api/<name>.js is one line: export const onRequest = pagesHandler(handler).
// The handler gets the Node-style req/res it was written for: method, url, lower-case
// headers, req.body parsed the way Vercel parses it, the raw body as a stream, and a res
// with setHeader/status/json/end. Configuration comes from context.env through lib/env.js
// (env() inside the handler and lib/*.js), never from process.env. Needs nodejs_compat.
//
// Differences from Vercel that this papers over:
//  - x-forwarded-for: Vercel overwrites it with the client address; Cloudflare appends to
//    whatever the client sent, so its first entry is client-controlled. The rate limiter
//    reads the first entry, so it is replaced with CF-Connecting-IP here.
//  - _headers does not apply to Functions on Cloudflare, but vercel.json's headers did apply
//    to the API on Vercel. siteHeaders() adds them to every response that doesn't set its own.
import { Readable } from "node:stream";
import { Buffer } from "node:buffer";
import envModule from "./env.js";
import vercelConfig from "../vercel.json";

const { withEnv } = envModule;

const SITE_HEADERS = (vercelConfig.headers || [])
  .filter((block) => block.source === "/(.*)")
  .flatMap((block) => block.headers);

// The security headers every response carried on Vercel. A header the handler set itself
// wins (auth-verify's Referrer-Policy: same-origin keeps its token away from other sites).
export function siteHeaders(headers) {
  for (const { key, value } of SITE_HEADERS) if (!headers.has(key)) headers.set(key, value);
  return headers;
}

export function jsonResponse(status, obj, extra) {
  const headers = new Headers(extra || {});
  headers.set("Content-Type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(obj), { status, headers: siteHeaders(headers) });
}

class HttpError extends Error {
  constructor(status, message) { super(message); this.statusCode = status; }
}

// Vercel's req.body: JSON, urlencoded and text/plain parsed, octet-stream as a Buffer,
// anything else undefined. Bad JSON is a 400 "Invalid JSON", thrown when req.body is read.
function parseBody(contentType, raw) {
  const type = String(contentType || "").split(";")[0].trim().toLowerCase();
  if (!type) return undefined;
  const text = raw.toString("utf8");
  if (type === "application/json") {
    try { return JSON.parse(text); } catch (e) { throw new HttpError(400, "Invalid JSON"); }
  }
  if (type === "application/x-www-form-urlencoded") {
    const out = {};
    for (const [k, v] of new URLSearchParams(text)) {
      out[k] = k in out ? [].concat(out[k], v) : v;
    }
    return out;
  }
  if (type === "text/plain") return text;
  if (type === "application/octet-stream") return raw;
  return undefined;
}

function nodeRequest(request, raw, bodyParser) {
  const url = new URL(request.url);
  const headers = {};
  for (const [k, v] of request.headers) headers[k] = v;
  const ip = request.headers.get("cf-connecting-ip") || "";
  if (ip) headers["x-forwarded-for"] = ip;
  else delete headers["x-forwarded-for"];       // wrangler dev: nothing trustworthy to put there
  headers.host = url.host;

  const req = Readable.from(raw.length ? [raw] : []);
  req.method = request.method;
  req.url = url.pathname + url.search;
  req.headers = headers;
  req.socket = { remoteAddress: ip || undefined };
  if (bodyParser !== false) {
    let parsed, done = false;
    Object.defineProperty(req, "body", {
      configurable: true, enumerable: true,
      get() { if (!done) { parsed = parseBody(headers["content-type"], raw); done = true; } return parsed; },
    });
  }
  return req;
}

function nodeResponse() {
  let finish;
  const ended = new Promise((resolve) => { finish = resolve; });
  const headers = new Map();                   // lower-case name -> [name, value]
  const res = {
    statusCode: 200,
    headersSent: false,
    setHeader(name, value) { headers.set(name.toLowerCase(), [name, value]); return res; },
    getHeader(name) { const h = headers.get(name.toLowerCase()); return h && h[1]; },
    hasHeader(name) { return headers.has(name.toLowerCase()); },
    removeHeader(name) { headers.delete(name.toLowerCase()); },
    status(code) { res.statusCode = code; return res; },
    json(obj) {
      if (!res.hasHeader("content-type")) res.setHeader("Content-Type", "application/json; charset=utf-8");
      return res.end(JSON.stringify(obj));
    },
    send(body) {
      if (body !== null && typeof body === "object" && !Buffer.isBuffer(body)) return res.json(body);
      return res.end(body);
    },
    end(body) {
      if (!res.headersSent) { res.headersSent = true; finish(body); }
      return res;
    },
  };
  const toResponse = (body) => {
    const out = new Headers();
    for (const [, [name, value]] of headers) {
      if (Array.isArray(value)) value.forEach((v) => out.append(name, String(v)));
      else out.set(name, String(value));
    }
    const status = res.statusCode;
    const empty = status === 204 || status === 304 || body === undefined || body === null;
    return new Response(empty ? null : body, { status, headers: siteHeaders(out) });
  };
  return { res, ended, toResponse };
}

export function pagesHandler(handler, opts = {}) {
  return async function onRequest(context) {
    const { request } = context;
    const raw = request.method === "GET" || request.method === "HEAD"
      ? Buffer.alloc(0) : Buffer.from(await request.arrayBuffer());
    const req = nodeRequest(request, raw, opts.bodyParser);
    const { res, ended, toResponse } = nodeResponse();
    try {
      await withEnv(context.env || {}, async () => {
        const run = Promise.resolve(handler(req, res));
        await Promise.race([ended, run]);
        await run;
      });
    } catch (e) {
      if (e && e.statusCode && !res.headersSent) {
        return new Response(e.message, { status: e.statusCode, headers: siteHeaders(new Headers({ "Content-Type": "text/plain; charset=utf-8" })) });
      }
      console.error(e);
      if (!res.headersSent) {
        return new Response("A server error has occurred", { status: 500, headers: siteHeaders(new Headers({ "Content-Type": "text/plain; charset=utf-8" })) });
      }
    }
    if (!res.headersSent) res.end();
    return toResponse(await ended);
  };
}
