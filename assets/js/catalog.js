// Catalog enhancements (T-1809). The pages work without this file: every item is listed,
// anchors scroll, snippets are selectable. This adds copy buttons and a client-side filter.
const live = document.getElementById("live");
const say = (text) => { if (live) live.textContent = text; };

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_e) { ok = false; }
    area.remove();
    return ok;
  }
}

document.querySelectorAll("button[data-copy]").forEach((btn) => {
  const code = btn.parentElement.querySelector("pre code");
  if (!code) return;
  const label = btn.textContent;
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    const ok = await copyText(code.textContent);
    say(ok ? "Copied" : "Copy failed. Select the text and copy it by hand.");
    if (!ok) return;
    btn.dataset.done = "";
    btn.textContent = "Copied";
    setTimeout(() => { delete btn.dataset.done; btn.textContent = label; }, 1800);
  });
});

const catalog = document.querySelector(".catalog");
if (catalog) {
  document.documentElement.classList.add("cat-js");
  const entries = [...catalog.querySelectorAll(".entry")];
  const groups = [...catalog.querySelectorAll(".group")];
  const bar = document.createElement("div");
  bar.className = "filter";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "Filter the catalog");
  const input = document.createElement("input");
  input.type = "search";
  input.id = "catalog-q";
  input.autocomplete = "off";
  const lab = document.createElement("label");
  lab.htmlFor = "catalog-q";
  lab.textContent = "Filter";
  bar.append(lab, input);
  const kinds = ["all", ...new Set(entries.map((e) => e.dataset.kind))];
  let kind = "all";
  const chips = kinds.map((k) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.dataset.kind = k;
    b.textContent = k === "all" ? "All" : k[0].toUpperCase() + k.slice(1) + "s";
    b.setAttribute("aria-pressed", String(k === "all"));
    b.addEventListener("click", () => { kind = k; apply(); });
    bar.append(b);
    return b;
  });
  catalog.parentElement.querySelector(".page-head").append(bar);
  const apply = () => {
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    for (const e of entries) {
      const hit = (kind === "all" || e.dataset.kind === kind) && (!q || e.textContent.toLowerCase().includes(q));
      e.hidden = !hit;
      if (hit) shown += 1;
    }
    for (const g of groups) g.hidden = !g.querySelector(".entry:not([hidden])");
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.kind === kind)));
    say(`${shown} of ${entries.length} items shown`);
  };
  input.addEventListener("input", apply);
}
