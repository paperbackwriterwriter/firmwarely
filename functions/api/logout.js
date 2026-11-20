// Cloudflare Pages Function for /api/logout: the Vercel handler in api/logout.js, run unchanged
// through lib/pages-adapter.mjs (same methods, status codes, JSON, cookies and redirects).
import handler from "../../api/logout.js";
import { pagesHandler } from "../../lib/pages-adapter.mjs";

export const onRequest = pagesHandler(handler);
