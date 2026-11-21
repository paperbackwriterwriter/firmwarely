// Cloudflare Pages Function for /api/me: the Vercel handler in api/me.js, run unchanged
// through lib/pages-adapter.mjs (same methods, status codes, JSON, cookies and redirects).
import handler from "../../api/me.js";
import { pagesHandler } from "../../lib/pages-adapter.mjs";

export const onRequest = pagesHandler(handler);
