// Cloudflare Pages Function for /api/auth-verify: the Vercel handler in api/auth-verify.js, run unchanged
// through lib/pages-adapter.mjs (same methods, status codes, JSON, cookies and redirects).
import handler from "../../api/auth-verify.js";
import { pagesHandler } from "../../lib/pages-adapter.mjs";

export const onRequest = pagesHandler(handler);
