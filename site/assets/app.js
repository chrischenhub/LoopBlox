'use strict';
const catalog = JSON.parse(document.getElementById('component-data').textContent);
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const detail = document.getElementById('component-detail');
const motion = document.querySelector('.motion-toggle');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let paused = reducedMotion.matches;

function updateMotion() {
  document.body.classList.toggle('paused', paused);
  motion.setAttribute('aria-pressed', String(paused));
  motion.textContent = reducedMotion.matches ? 'Motion reduced' : paused ? 'Resume motion ▷' : 'Pause motion Ⅱ';
  motion.disabled = reducedMotion.matches;
}

motion.addEventListener('click', () => { paused = !paused; updateMotion(); });
reducedMotion.addEventListener('change', () => { paused = reducedMotion.matches; updateMotion(); });

document.querySelector('.family-grid').addEventListener('click', event => {
  const button = event.target.closest('[data-component]');
  if (!button) return;
  const name = button.dataset.component;
  const component = catalog[name];
  document.querySelectorAll('[data-component]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  detail.innerHTML = `<div><span class="eyebrow">${escapeHTML(component.family.label)}</span><h3 class="prompt">${escapeHTML(component.plain)}</h3><p class="ident">${escapeHTML(name)}</p><p>${escapeHTML(component.description)}</p></div>
    <dl class="contract-facts"><div><dt>BEHAVIOR</dt><dd>${escapeHTML(component.contract.behavior)}</dd></div><div><dt>MODEL / TOOL CALLS</dt><dd>${escapeHTML(component.contract.model_calls)}</dd></div><div><dt>RETURN</dt><dd>${escapeHTML(component.contract.returns)}</dd></div></dl>
    <a class="link-out" href="component-contracts.md" download>Download reference ↓</a>`;
});
updateMotion();
