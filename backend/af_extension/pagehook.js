// MAIN world: when the page opens a file picker, ask the extension to upload the product-link photos instead.
(() => {
  if (window.__afHook) return;
  window.__afHook = true;
  const on = () => document.documentElement.getAttribute("data-af-img") === "1";
  const want = (inp) => {
    if (!inp.isConnected) { inp.style.display = "none"; inp.setAttribute("data-af-detached", "1"); (document.body || document.documentElement).appendChild(inp); }
    inp.dispatchEvent(new CustomEvent("af-want-images", { bubbles: true, composed: true }));
  };
  const origClick = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type === "file" && on()) return want(this);
    return origClick.apply(this, arguments);
  };
  const origPicker = HTMLInputElement.prototype.showPicker;
  if (origPicker) HTMLInputElement.prototype.showPicker = function () {
    if (this.type === "file" && on()) return want(this);
    return origPicker.apply(this, arguments);
  };
})();
