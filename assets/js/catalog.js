// Each component and source file remains reachable without JavaScript.
const live = document.getElementById("live");

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const focused = document.activeElement;
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { /* Selectable source stays visible. */ }
    area.remove();
    focused?.focus({ preventScroll: true });
    return ok;
  }
}

for (const button of document.querySelectorAll("button[data-copy]")) {
  const code = button.closest(".snip")?.querySelector("pre code");
  if (!code) continue;
  const label = button.textContent;
  let reset;
  button.hidden = false;
  button.addEventListener("click", async () => {
    const ok = await copyText(code.textContent);
    button.toggleAttribute("data-done", ok);
    button.textContent = ok ? "Copied" : "Select and copy";
    if (live) live.textContent = ok ? "Copied to clipboard." : "Select the command or file and copy it manually.";
    clearTimeout(reset);
    reset = setTimeout(() => { button.removeAttribute("data-done"); button.textContent = label; }, 1800);
  });
}

function enableLibrary(catalog) {
  const search = catalog.querySelector(".catalog-search");
  const field = search.querySelector("input");
  const filters = Array.from(catalog.querySelectorAll("[data-filter]"));
  const groups = Array.from(catalog.querySelectorAll(".group"));
  const entries = Array.from(catalog.querySelectorAll(".entry"), node => ({
    node, text: [node.textContent, node.dataset.search, node.dataset.kind].join(" ").toLowerCase()
  }));
  const empty = catalog.querySelector(".catalog-empty");
  let kind = "all";
  search.hidden = false;

  function render() {
    const terms = field.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let matches = 0;
    for (const {node, text} of entries) {
      const visible = (kind === "all" || kind === node.dataset.kind) && terms.every(term => text.includes(term));
      node.hidden = !visible;
      if (visible) matches += 1;
    }
    for (const group of groups) {
      const count = group.querySelectorAll(".entry:not([hidden])").length;
      group.hidden = !count;
      group.querySelector("h2 small").textContent = count;
    }
    for (const filter of filters) {
      if (filter.dataset.filter === kind) filter.setAttribute("aria-current", "true");
      else filter.removeAttribute("aria-current");
    }
    empty.hidden = matches !== 0;
    live.textContent = matches + (matches === 1 ? " component shown" : " components shown");
  }

  function fromLocation() {
    const url = new URL(location.href);
    // A direct component anchor always exposes that row, even with an older search URL.
    const row = document.getElementById(url.hash.slice(1))?.closest(".entry");
    const filter = filters.find(link => link.hash === url.hash);
    field.value = row ? "" : url.searchParams.get("q") || "";
    kind = filter?.dataset.filter || "all";
    render();
  }

  function updateLocation(method) {
    const url = new URL(location.href);
    const query = field.value.trim();
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    url.hash = kind === "all" ? "" : filters.find(link => link.dataset.filter === kind).hash;
    if (url.href !== location.href) history[method](null, "", url);
    render();
  }

  for (const filter of filters) {
    filter.addEventListener("click", event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      kind = filter.dataset.filter;
      updateLocation("pushState");
      // Selecting a sticky collection far down the page should land on its results.
      if (search.getBoundingClientRect().bottom < 0) search.scrollIntoView({ block: "start", behavior: "instant" });
    });
  }
  field.addEventListener("input", () => updateLocation("replaceState"));
  empty.querySelector("[data-reset]").addEventListener("click", () => {
    kind = "all";
    field.value = "";
    updateLocation("pushState");
    field.focus();
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) return;
    if (event.target.closest("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    field.focus();
  });
  window.addEventListener("popstate", fromLocation);
  window.addEventListener("hashchange", fromLocation);
  fromLocation();
}

const catalog = document.querySelector(".catalog");
if (catalog) enableLibrary(catalog);
