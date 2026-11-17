// Hivemill v2 motion. Vanilla ES module, no dependencies.
// Transform and opacity only (see v2.css). Does nothing when the visitor
// prefers reduced motion; with JS off every element is already visible.
const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (!calm) {
  document.documentElement.classList.add("js");

  // 1. Reveal elements once as they scroll into view.
  const items = document.querySelectorAll("[data-reveal]");
  const seen = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-in");
      seen.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -10% 0px", threshold: 0.1 });
  items.forEach((el, i) => {
    el.style.setProperty("--d", `${(i % 3) * 90}ms`);
    seen.observe(el);
  });

  // 2. The pipeline piece lights its five steps in order, once, when seen.
  const pipe = document.querySelector(".pipe");
  if (pipe) {
    pipe.dataset.live = "";
    const steps = [...pipe.children];
    const run = () => steps.forEach((li, i) => setTimeout(() => li.classList.add("is-on"), 350 + i * 700));
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { run(); io.disconnect(); }
    }, { threshold: 0.4 });
    io.observe(pipe);
  }
}
