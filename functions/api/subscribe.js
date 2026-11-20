// Cloudflare Pages Function for /api/subscribe: the Vercel handler in api/subscribe.js, run unchanged
// through lib/pages-adapter.mjs (same methods, status codes, JSON, cookies and redirects).
import handler from "../../api/subscribe.js";
import { pagesHandler } from "../../lib/pages-adapter.mjs";

export const onRequest = pagesHandler(handler);
