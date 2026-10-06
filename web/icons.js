/* OpenSourceGuard 共享 SVG 图标精灵。
   注入一次即可在所有页面通过 <svg class="icon"><use href="#i-name"/></svg> 使用。
   风格对齐 Lucide（24×24、stroke=currentColor、圆角端点）。 */
(function () {
  "use strict";
  const S = (id, body) => `<symbol id="i-${id}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</symbol>`;
  const symbols = [
    S("shield-check", '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>'),
    S("shield", '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/>'),
    S("shield-alert", '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="M12 8v4"/><path d="M12 16h.01"/>'),
    S("activity", '<path d="M3 12h4l3-7 4 14 3-7h4"/>'),
    S("folder-git-2", '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><circle cx="13" cy="14" r="1.8"/><path d="M15 14h2.5"/><path d="M10.5 16.6V18"/>'),
    S("layers", '<path d="m12 2 9 4.5-9 4.5-9-4.5z"/><path d="m3 11.5 9 4.5 9-4.5"/><path d="m3 16.5 9 4.5 9-4.5"/>'),
    S("rocket", '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91 0z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>'),
    S("swords", '<path d="m14.5 17.5L3 6V3h3l11.5 11.5"/><path d="m13 19 6-6"/><path d="m16 16 4 4"/><path d="m19 21 2-2"/>'),
    S("zap", '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>'),
    S("lock", '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
    S("sparkles", '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/>'),
    S("settings", '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
    S("chevron-right", '<path d="m9 18 6-6-6-6"/>'),
    S("chevron-down", '<path d="m6 9 6 6 6-6"/>'),
    S("check-circle-2", '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
    S("map-pin", '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>'),
    S("puzzle", '<path d="M19.4 7.9c.05.32-.06.65-.29.88l-1.57 1.57c-.47.47-.71 1.09-.71 1.7s.24 1.24.71 1.71l1.61 1.61c.24.24.34.58.28.9-.07.47-.48.8-.97.97a2.5 2.5 0 1 1-3.21 3.21c-.17-.49-.5-.9-.97-.97a.98.98 0 0 1-.84-.28l-1.61-1.61a2.4 2.4 0 0 0-1.7-.71 2.4 2.4 0 0 0-1.71.71l-1.57 1.57c-.23.23-.56.34-.88.29-.49-.07-.84-.5-1.02-.97A2.5 2.5 0 1 1 1.5 13.9c.18-.46.53-.9 1.02-.97.32-.05.65.06.88.29l1.57 1.57c.47.47 1.09.71 1.7.71s1.24-.24 1.71-.71l1.61-1.61a.98.98 0 0 1 .9-.28c.47.07.8.48.97.97a2.5 2.5 0 1 0 3.21-3.21c-.49-.17-.9-.5-.97-.97a.98.98 0 0 1 .28-.9l1.53-1.53c.47-.47 1.09-.71 1.7-.71s1.24.24 1.71.71l1.56 1.57Z"/>'),
    S("flask-conical", '<path d="M10 2v7.5a2 2 0 0 1-.21.9L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.07-10.13a2 2 0 0 1-.21-.9V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>'),
    S("test-tube", '<path d="M14.5 2v17.5c0 1.4-1.1 2.5-2.5 2.5s-2.5-1.1-2.5-2.5V2"/><path d="M8.5 2h7"/><path d="M7.5 16h9"/>'),
    S("file-x", '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="m14.5 12.5-5 5"/><path d="m9.5 12.5 5 5"/>'),
    S("list-restart", '<path d="M4 6h10"/><path d="M4 12h8"/><path d="M4 18h8"/><path d="m16 13 3 3-3 3"/><path d="M19 16h-4"/>'),
    S("copy", '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'),
    S("download", '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>'),
    S("alert-circle", '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>'),
    S("tag", '<path d="M12.59 2.59A2 2 0 0 0 11.17 2H4a2 2 0 0 0-2 2v7.17a2 2 0 0 0 .59 1.42l8.7 8.7a2.43 2.43 0 0 0 3.42 0l6.58-6.58a2.43 2.43 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".6" fill="currentColor"/>'),
    S("file-text", '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'),
    S("list-checks", '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>'),
    S("scale", '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>'),
    S("book-open", '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>'),
    S("git-branch", '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>'),
    S("play-circle", '<circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>'),
    S("pause", '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>'),
    S("menu", '<line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/>'),
    S("x", '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
    S("search", '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
    S("globe", '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'),
    S("terminal", '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>'),
    S("info", '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'),
    S("check", '<path d="M20 6 9 17l-5-5"/>'),
    S("arrow-up-right", '<path d="M7 17 17 7"/><path d="M7 7h10v10"/>'),
    S("arrow-right", '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>'),
    S("trophy", '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>'),
    S("code", '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>'),
    S("refresh", '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>'),
    S("upload", '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>'),
    S("folder", '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    S("issue", '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>'),
    S("user", '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
    S("git-pull-request", '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" x2="6" y1="9" y2="21"/>'),
    S("clock", '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'),
    S("external-link", '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h6"/>'),
    S("send", '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>'),
    S("message-square", '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
    S("wand", '<path d="m15 4V2"/><path d="m15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8 19 13"/><path d="M15 9h.01"/><path d="M17.8 6.2 19 5"/><path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/>'),
  ];
  const SVG_NS = "http://www.w3.org/2000/svg";
  const parent = document.body || document.documentElement;
  const attach = (sprite) => parent.insertBefore(sprite, parent.firstChild);
  const host = document.createElementNS(SVG_NS, "svg");
  host.setAttribute("aria-hidden", "true");
  host.setAttribute("style", "display:none");
  host.innerHTML = symbols.join("");
  if (host.namespaceURI === SVG_NS && host.firstElementChild && host.firstElementChild.namespaceURI === SVG_NS) {
    attach(host);
  } else {
    const parsed = new DOMParser().parseFromString(`<svg xmlns="${SVG_NS}">${symbols.join("")}</svg>`, "image/svg+xml");
    const fallback = document.createElementNS(SVG_NS, "svg");
    fallback.setAttribute("aria-hidden", "true");
    fallback.setAttribute("style", "display:none");
    for (const node of Array.from(parsed.documentElement.childNodes)) {
      fallback.appendChild(document.importNode(node, true));
    }
    attach(fallback);
  }
})();
