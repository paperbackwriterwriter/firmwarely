// Cloudflare Pages Function for /api/stripe-webhook. The logic is api/stripe-webhook.js's
// handleEvent, shared with the Vercel function; only the request plumbing differs.
//
// The signature is checked against the exact bytes Stripe sent: the body is read once with
// arrayBuffer() (not text(), which would re-encode anything that isn't valid UTF-8) and
// handed over as a Buffer, the same type the Vercel function's readRaw() produces.
import { Buffer } from "node:buffer";
import { handleEvent } from "../../api/stripe-webhook.js";
import { jsonResponse, siteHeaders } from "../../lib/pages-adapter.mjs";

export async function onRequest({ request, env }) {
  if (request.method !== "POST") {
    return new Response(null, { status: 405, headers: siteHeaders(new Headers({ Allow: "POST" })) });
  }
  const raw = Buffer.from(await request.arrayBuffer());
  const out = await handleEvent(raw, request.headers.get("stripe-signature") || "", env);
  return jsonResponse(out.status, out.body);
}
