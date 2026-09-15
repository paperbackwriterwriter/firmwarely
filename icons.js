/* Device-family icons: stylised line art in the site palette, one path set per family.
   Single source of truth. The homepage reads this file in the browser; scripts/build_pages.py
   parses the JSON between the markers for the generated pages. Which family a device belongs
   to is decided once, in scripts/fetch.py (the `icon` field in devices.json).
   Draw inside a 64x64 box, stroke only; class "g" = green stroke, class "f" = green fill. */
window.FW_ICONS = /*json*/{
 "router": "<rect x=\"6\" y=\"34\" width=\"52\" height=\"16\" rx=\"4\"/><path d=\"M16 34V16M48 34V16\"/><circle cx=\"16\" cy=\"13\" r=\"2.5\"/><circle cx=\"48\" cy=\"13\" r=\"2.5\"/><circle class=\"f\" cx=\"18\" cy=\"42\" r=\"1.8\"/><circle class=\"f\" cx=\"26\" cy=\"42\" r=\"1.8\"/><circle cx=\"34\" cy=\"42\" r=\"1.8\"/><path d=\"M30 26a8 8 0 0 1 4 0M27 21a14 14 0 0 1 10 0\"/>",
 "nas": "<rect x=\"14\" y=\"8\" width=\"36\" height=\"48\" rx=\"4\"/><rect x=\"20\" y=\"14\" width=\"24\" height=\"8\" rx=\"1.5\"/><rect x=\"20\" y=\"26\" width=\"24\" height=\"8\" rx=\"1.5\"/><rect x=\"20\" y=\"38\" width=\"24\" height=\"8\" rx=\"1.5\"/><circle class=\"f\" cx=\"42\" cy=\"51\" r=\"1.8\"/><path d=\"M24 18h4M24 30h4M24 42h4\"/>",
 "app": "<rect x=\"8\" y=\"12\" width=\"48\" height=\"40\" rx=\"4\"/><path d=\"M8 22h48\"/><circle class=\"f\" cx=\"14\" cy=\"17\" r=\"1.6\"/><circle cx=\"20\" cy=\"17\" r=\"1.6\"/><path d=\"M16 32h14M16 40h22M36 32h12\"/>",
 "camera": "<rect x=\"8\" y=\"22\" width=\"34\" height=\"20\" rx=\"4\"/><path d=\"M42 28l12-6v20l-12-6\"/><circle cx=\"24\" cy=\"32\" r=\"5\"/><circle class=\"f\" cx=\"24\" cy=\"32\" r=\"1.6\"/><path d=\"M24 42v10M16 52h16\"/>",
 "doorbell": "<rect x=\"22\" y=\"6\" width=\"20\" height=\"52\" rx=\"6\"/><circle cx=\"32\" cy=\"20\" r=\"6\"/><circle class=\"f\" cx=\"32\" cy=\"20\" r=\"2\"/><circle class=\"g\" cx=\"32\" cy=\"44\" r=\"4.5\"/><path d=\"M26 32h12\"/>",
 "speaker": "<rect x=\"18\" y=\"8\" width=\"28\" height=\"48\" rx=\"9\"/><path d=\"M25 20h14M25 27h14M25 34h14\"/><circle class=\"f\" cx=\"32\" cy=\"47\" r=\"2.2\"/>",
 "hub": "<circle cx=\"32\" cy=\"32\" r=\"17\"/><circle class=\"f\" cx=\"32\" cy=\"32\" r=\"3\"/><path d=\"M32 7v8M32 49v8M7 32h8M49 32h8\"/><path class=\"g\" d=\"M32 22a10 10 0 0 1 10 10\"/>",
 "console": "<path d=\"M18 22h28a10 10 0 0 1 10 10l2 12a6 6 0 0 1-11 3l-4-7H21l-4 7a6 6 0 0 1-11-3l2-12a10 10 0 0 1 10-10z\"/><path d=\"M22 30v8M18 34h8\"/><circle class=\"f\" cx=\"44\" cy=\"31\" r=\"1.8\"/><circle cx=\"48\" cy=\"36\" r=\"1.8\"/><circle cx=\"40\" cy=\"36\" r=\"1.8\"/>",
 "drone": "<rect x=\"26\" y=\"28\" width=\"12\" height=\"10\" rx=\"3\"/><path d=\"M26 31L17 24M38 31l9-7M26 35l-9 7M38 35l9 7\"/><path d=\"M8 22h18M38 22h18M8 44h18M38 44h18\"/><circle class=\"f\" cx=\"32\" cy=\"33\" r=\"1.5\"/>",
 "ebike": "<circle cx=\"16\" cy=\"44\" r=\"10\"/><circle cx=\"48\" cy=\"44\" r=\"10\"/><path d=\"M16 44l10-20h12l10 20M26 24l-4-8h6M38 24l4 20M26 24l8 12h8\"/><rect class=\"f\" x=\"27\" y=\"32\" width=\"9\" height=\"6\" rx=\"1.5\"/>",
 "printer": "<path d=\"M8 10h48v46H8z\"/><path d=\"M8 20h48\"/><path d=\"M28 20v10h8V20\"/><path class=\"g\" d=\"M32 30v8\"/><path d=\"M14 50h36\"/><path d=\"M20 46h24\"/>",
 "tv": "<rect x=\"6\" y=\"12\" width=\"52\" height=\"32\" rx=\"4\"/><path d=\"M22 52h20M32 44v8\"/><path class=\"g\" d=\"M24 34l6-8 5 5 7-10\"/>",
 "laptop": "<rect x=\"12\" y=\"12\" width=\"40\" height=\"26\" rx=\"3\"/><path d=\"M6 46h52l-4 6H10z\"/><circle class=\"f\" cx=\"32\" cy=\"16\" r=\"1.5\"/>",
 "headphones": "<path d=\"M12 40V32a20 20 0 0 1 40 0v8\"/><rect x=\"8\" y=\"36\" width=\"12\" height=\"16\" rx=\"4\"/><rect x=\"44\" y=\"36\" width=\"12\" height=\"16\" rx=\"4\"/><circle class=\"f\" cx=\"14\" cy=\"44\" r=\"1.6\"/>",
 "print": "<rect x=\"10\" y=\"26\" width=\"44\" height=\"22\" rx=\"4\"/><path d=\"M20 26V12h24v14M20 48v8h24v-8\"/><path d=\"M26 40h12\"/><circle class=\"f\" cx=\"46\" cy=\"33\" r=\"1.8\"/>",
 "watch": "<rect x=\"18\" y=\"18\" width=\"28\" height=\"28\" rx=\"8\"/><path d=\"M24 18l2-10h12l2 10M24 46l2 10h12l2-10\"/><path class=\"g\" d=\"M32 26v7l5 3\"/>",
 "keyboard": "<rect x=\"6\" y=\"20\" width=\"52\" height=\"26\" rx=\"4\"/><path d=\"M14 28h4M22 28h4M30 28h4M38 28h4M46 28h4M14 36h4M22 36h4M30 36h4M38 36h4M46 36h4\"/><path class=\"g\" d=\"M22 42h20\"/>",
 "tablet": "<rect x=\"16\" y=\"8\" width=\"32\" height=\"48\" rx=\"4\"/><path d=\"M24 18h16M24 26h16M24 34h10\"/><circle class=\"f\" cx=\"32\" cy=\"50\" r=\"1.6\"/>",
 "board": "<rect x=\"14\" y=\"18\" width=\"36\" height=\"28\" rx=\"3\"/><path d=\"M20 18v-6M28 18v-6M36 18v-6M44 18v-6M20 46v6M28 46v6M36 46v6M44 46v6\"/><rect x=\"24\" y=\"26\" width=\"16\" height=\"12\" rx=\"1.5\"/><circle class=\"f\" cx=\"44\" cy=\"41\" r=\"1.5\"/>"
}/*end*/;
/* Inline SVG for one family; falls back to the generic device box. */
window.fwIcon = function (key, cls) {
  var d = window.FW_ICONS[key] || window.FW_ICONS.app;
  return '<svg class="' + (cls || "ico") + '" viewBox="0 0 64 64" aria-hidden="true">' + d + '</svg>';
};
