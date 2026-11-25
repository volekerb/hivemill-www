// Copy buttons for install steps. Without JS the commands stay selectable text.
for (const btn of document.querySelectorAll("button.copy[data-copy]")) {
  // Space is reserved in CSS (visibility) so showing the button shifts nothing.
  if (navigator.clipboard) btn.classList.add("ready");
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
