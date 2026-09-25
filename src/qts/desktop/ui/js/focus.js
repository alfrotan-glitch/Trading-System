/* Shared modal keyboard model: contain focus, Escape, and restore invoking control. */
export function focusDialog(dialog, onEscape) {
  const previous = document.activeElement;
  const siblings = [...document.body.children].filter((n) => !n.contains(dialog));
  const inert = siblings.map((n) => [n, n.inert]);
  siblings.forEach((n) => { n.inert = true; });
  const items = () => [...dialog.querySelectorAll('button, input, select, textarea, a[href], [tabindex="0"]')].filter((n) => !n.disabled && !n.closest("[hidden]"));
  dialog.tabIndex = -1;
  function key(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); onEscape?.(); }
    if (e.key === "Tab") {
      const list = items(), first = list[0] || dialog, last = list.at(-1) || dialog;
      if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || document.activeElement === dialog)) { e.preventDefault(); first.focus(); }
    }
  }
  document.addEventListener("keydown", key, true);
  (items()[0] || dialog).focus();
  return () => {
    document.removeEventListener("keydown", key, true);
    inert.forEach(([n, old]) => { n.inert = old; });
    if (previous?.isConnected) previous.focus();
  };
}
