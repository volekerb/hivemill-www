// Copy buttons for install steps. Without JS the commands stay selectable text.
for (const btn of document.querySelectorAll("button.copy[data-copy]")) {
  btn.hidden = !navigator.clipboard;
  btn.addEventListener("click", async () => {
    const text = document.getElementById(btn.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
    } catch (err) {
      btn.textContent = "Select and copy";
    }
    setTimeout(() => { btn.textContent = "Copy"; }, 1800);
  });
}
