// Cloudflare Pages Function for /api/unsubscribe: the Vercel handler in api/unsubscribe.js, run unchanged
// through lib/pages-adapter.mjs (same methods, status codes, JSON, cookies and redirects).
import handler from "../../api/unsubscribe.js";
import { pagesHandler } from "../../lib/pages-adapter.mjs";

export const onRequest = pagesHandler(handler);
