// Cloudflare Pages Function for /api/contact: the Vercel handler in api/contact.js, run unchanged
// through lib/pages-adapter.mjs (same methods, status codes, JSON, cookies and redirects).
import handler from "../../api/contact.js";
import { pagesHandler } from "../../lib/pages-adapter.mjs";

export const onRequest = pagesHandler(handler);
