
const slides = document.querySelectorAll('.slide');
const list = document.getElementById('slide-list');
const counter = document.getElementById('counter');
const stage = document.getElementById('stage');
const wrap = document.getElementById('stage-wrap');

let current = 1;
let total = slides.length;
let scale = 1.0;

function goto(n, push=true) {
  n = Math.max(1, Math.min(total, n));
  if (n === current && !push) {
    show();
    return;
  }
  current = n;
  if (push) {
    history.replaceState(null, '', '#' + n);
  }
  show();
}

function show() {
  slides.forEach(s => s.classList.remove('active'));
  const s = document.querySelector(`.slide[data-slide="${current}"]`);
  if (s) s.classList.add('active');
  // highlight sidebar
  document.querySelectorAll('#slide-list li').forEach(li => li.classList.remove('active'));
  const li = document.querySelector(`#slide-list li[data-slide="${current}"]`);
  if (li) {
    li.classList.add('active');
    li.scrollIntoView({ block: 'nearest' });
  }
  counter.textContent = current + ' / ' + total;
  rescale();
  // re-typeset math
  if (window.MathJax && window.MathJax.typesetPromise) {
    window.MathJax.typesetPromise([s]);
  }
}

function rescale() {
  const s = document.querySelector('.slide.active');
  if (!s) return;
  // Reset to intrinsic slide size (set in style by width:N in; height:N in;)
  const sw = s.offsetWidth, sh = s.offsetHeight;
  const avw = stage.clientWidth - 40, avh = stage.clientHeight - 40;
  const f = Math.min(avw / sw, avh / sh, 4);
  s.style.zoom = (f * scale).toFixed(4);
}

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { goto(current + 1); e.preventDefault(); }
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { goto(current - 1); e.preventDefault(); }
  else if (e.key === 'Home') { goto(1); e.preventDefault(); }
  else if (e.key === 'End') { goto(total); e.preventDefault(); }
  else if (e.key === 'e' || e.key === 'E') { document.body.classList.toggle('edit-mode'); }
  else if (e.key === '+' || e.key === '=') { scale = Math.min(4, scale * 1.1); rescale(); }
  else if (e.key === '-' || e.key === '_') { scale = Math.max(0.2, scale / 1.1); rescale(); }
  else if (e.key === '0') { scale = 1.0; rescale(); }
  else if (e.key === 'f' || e.key === 'F') { toggleFullscreen(); }
});

function toggleFullscreen() {
  const s = document.querySelector('.slide.active');
  if (s && s.requestFullscreen) s.requestFullscreen();
  else if (document.fullscreenElement) document.exitFullscreen();
}

list.addEventListener('click', e => {
  const li = e.target.closest('li[data-slide]');
  if (li) goto(parseInt(li.dataset.slide, 10));
});

window.addEventListener('resize', rescale);
window.addEventListener('hashchange', () => {
  const n = parseInt(location.hash.slice(1), 10);
  if (!isNaN(n)) goto(n, false);
});

// ============================================================
// Edit mode
// ============================================================
const editor = document.getElementById('editor');
const STORAGE_KEY = 'pptx2html:edits';
let selectedShape = null;
let savedEdits = {};  // { "slide_N": { shapeId: {left, top, width, height, rotation, html} } }

function loadEdits() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) savedEdits = JSON.parse(raw);
  } catch (e) {
    savedEdits = {};
  }
}

function saveEdits() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(savedEdits));
  } catch (e) {
    console.warn('Failed to save edits:', e);
  }
}

function shapeId(shape) {
  // Use a stable id: index within slide + tag
  const slide = shape.closest('.slide');
  if (!slide) return null;
  const all = Array.from(slide.querySelectorAll('.shape, .pic, .group, .bg-image, .bg-solid'));
  const idx = all.indexOf(shape);
  return idx;
}

function parseStyleNum(style, prop) {
  const m = style.match(new RegExp(prop + ':\\s*(-?[0-9.]+)in'));
  return m ? parseFloat(m[1]) : 0;
}

function getShapeInfo(shape) {
  const cs = shape.style;
  const left = parseStyleNum(cs.cssText, 'left') || parseStyleNum(cs.left, 'left') || 0;
  const top = parseStyleNum(cs.cssText, 'top') || parseStyleNum(cs.top, 'top') || 0;
  const width = parseStyleNum(cs.cssText, 'width') || parseStyleNum(cs.width, 'width') || 0;
  const height = parseStyleNum(cs.cssText, 'height') || parseStyleNum(cs.height, 'height') || 0;
  let rotation = 0;
  const rotM = cs.cssText.match(/transform:\s*rotate\(([0-9.-]+)deg\)/);
  if (rotM) rotation = parseFloat(rotM[1]);
  // Text content: pick the tx-body or pic or innerHTML
  let text = '';
  if (shape.classList.contains('pic') || shape.classList.contains('ole')) {
    text = shape.getAttribute('alt') || shape.getAttribute('src') || '';
  } else {
    const tx = shape.querySelector('.tx-body') || shape.querySelector('.text-overlay .tx-body');
    if (tx) text = tx.innerText || tx.textContent || '';
    else text = shape.innerText || '';
  }
  const id = shapeId(shape);
  return { id, left, top, width, height, rotation, text, tag: shape.tagName.toLowerCase(), classes: shape.className };
}

function applyShapeEdits(slideEl, idx, edits) {
  const shape = Array.from(slideEl.querySelectorAll('.shape, .pic, .group, .bg-image, .bg-solid'))[idx];
  if (!shape) return;
  // We have to be careful: the inline style has many properties. We'll preserve the original
  // style attribute and modify only what we know about.
  if (edits.left !== undefined) shape.style.left = edits.left + 'in';
  if (edits.top !== undefined) shape.style.top = edits.top + 'in';
  if (edits.width !== undefined) shape.style.width = edits.width + 'in';
  if (edits.height !== undefined) shape.style.height = edits.height + 'in';
  if (edits.rotation !== undefined) {
    // Replace or add transform: rotate
    const m = shape.style.cssText.match(/transform:\s*rotate\([0-9.-]+deg\)/);
    if (m) {
      shape.style.cssText = shape.style.cssText.replace(/transform:\s*rotate\([0-9.-]+deg\)/, `transform:rotate(${edits.rotation}deg)`);
    } else if (edits.rotation !== 0) {
      shape.style.transform = `rotate(${edits.rotation}deg)`;
    }
  }
  if (edits.text !== undefined) {
    const tx = shape.querySelector('.tx-body') || shape.querySelector('.text-overlay .tx-body');
    if (tx) {
      // Replace the whole tx-body. Use plain text -> wrap in <p>.
      const lines = edits.text.split(/\n/);
      const pHtml = lines.map(l => `<p>${escapeHtml(l)}</p>`).join('');
      tx.innerHTML = pHtml;
    } else if (shape.classList.contains('pic') || shape.classList.contains('ole')) {
      shape.setAttribute('alt', edits.text);
    }
  }
}

function restoreEdits() {
  for (const key of Object.keys(savedEdits)) {
    const m = key.match(/^slide_(\d+)$/);
    if (!m) continue;
    const slideEl = document.querySelector(`.slide[data-slide="${m[1]}"]`);
    if (!slideEl) continue;
    const edits = savedEdits[key];
    for (const idxStr of Object.keys(edits)) {
      applyShapeEdits(slideEl, parseInt(idxStr, 10), edits[idxStr]);
    }
  }
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function selectShape(shape) {
  if (selectedShape) selectedShape.classList.remove('selected');
  selectedShape = shape;
  if (!shape) {
    editor.classList.remove('open');
    return;
  }
  selectedShape.classList.add('selected');
  const info = getShapeInfo(shape);
  editor.innerHTML = `
    <div class="ed-header">
      <span>${info.classes.split(' ')[0] || 'shape'}</span>
      <button class="ed-close" onclick="selectShape(null)">×</button>
    </div>
    <div class="ed-row">
      <label>X (in) <input type="number" step="0.01" id="ed-left" value="${info.left.toFixed(3)}"></label>
      <label>Y (in) <input type="number" step="0.01" id="ed-top" value="${info.top.toFixed(3)}"></label>
    </div>
    <div class="ed-row">
      <label>W (in) <input type="number" step="0.01" id="ed-width" value="${info.width.toFixed(3)}"></label>
      <label>H (in) <input type="number" step="0.01" id="ed-height" value="${info.height.toFixed(3)}"></label>
    </div>
    <div class="ed-row">
      <label>Rot (°) <input type="number" step="0.5" id="ed-rot" value="${info.rotation.toFixed(2)}"></label>
    </div>
    ${info.classes.includes('pic') || info.classes.includes('ole') ?
      `<label>alt <input type="text" id="ed-alt" value="${escapeHtml(info.text)}"></label>`
      :
      `<label>Текст <textarea id="ed-text" rows="4">${escapeHtml(info.text)}</textarea></label>`
    }
    <div class="ed-buttons">
      <button class="ed-apply">Применить</button>
      <button class="ed-save">Сохранить</button>
    </div>
  `;
  editor.classList.add('open');
  // Wire up apply
  const apply = () => {
    const left = parseFloat(document.getElementById('ed-left').value);
    const top = parseFloat(document.getElementById('ed-top').value);
    const width = parseFloat(document.getElementById('ed-width').value);
    const height = parseFloat(document.getElementById('ed-height').value);
    const rot = parseFloat(document.getElementById('ed-rot').value);
    const textEl = document.getElementById('ed-text') || document.getElementById('ed-alt');
    const text = textEl ? textEl.value : undefined;
    applyShapeEdits(shape.closest('.slide'), info.id, { left, top, width, height, rotation: rot, text });
    rescale();
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([shape.closest('.slide')]);
    }
  };
  editor.querySelector('.ed-apply').onclick = apply;
  editor.querySelector('.ed-save').onclick = () => {
    apply();
    const key = `slide_${current}`;
    if (!savedEdits[key]) savedEdits[key] = {};
    // Merge with current values
    const fresh = getShapeInfo(shape);
    savedEdits[key][info.id] = {
      left: fresh.left, top: fresh.top, width: fresh.width, height: fresh.height,
      rotation: fresh.rotation, text: fresh.text,
    };
    saveEdits();
    flashSaved();
  };
}

function flashSaved() {
  const f = document.createElement('div');
  f.className = 'ed-flash';
  f.textContent = '✓ Сохранено';
  document.body.appendChild(f);
  setTimeout(() => f.remove(), 1500);
}

// Edit-mode click handler
document.addEventListener('click', e => {
  if (!document.body.classList.contains('edit-mode')) return;
  if (e.target.closest('#editor')) return;  // ignore clicks inside the editor
  if (e.target.closest('#toolbar')) return;
  if (e.target.closest('#sidebar')) return;
  // Walk up to find a shape
  let t = e.target;
  while (t && t !== document.body) {
    if (t.classList && (
      t.classList.contains('shape') || t.classList.contains('pic') ||
      t.classList.contains('group') || t.classList.contains('bg-image') ||
      t.classList.contains('bg-solid') || t.classList.contains('ole')
    )) {
      selectShape(t);
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    t = t.parentElement;
  }
  selectShape(null);
});

// Drag-to-move
let drag = null;
document.addEventListener('mousedown', e => {
  if (!document.body.classList.contains('edit-mode')) return;
  if (!selectedShape) return;
  if (e.target.closest('#editor')) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  // Only start drag if click was on selected shape itself
  if (e.target !== selectedShape && !selectedShape.contains(e.target)) return;
  const info = getShapeInfo(selectedShape);
  drag = {
    shape: selectedShape,
    startX: e.clientX,
    startY: e.clientY,
    origLeft: info.left,
    origTop: info.top,
    slideRect: selectedShape.closest('.slide').getBoundingClientRect(),
  };
  e.preventDefault();
});

document.addEventListener('mousemove', e => {
  if (!drag) return;
  // Convert pixel delta to inches
  const sw = parseFloat(selectedShape.closest('.slide').style.width);
  const slideW = drag.slideRect.width;
  const dxIn = (e.clientX - drag.startX) * (sw / slideW);
  const dyIn = (e.clientY - drag.startY) * (sw / slideW);
  drag.shape.style.left = (drag.origLeft + dxIn).toFixed(3) + 'in';
  drag.shape.style.top = (drag.origTop + dyIn).toFixed(3) + 'in';
});

document.addEventListener('mouseup', () => {
  if (drag) {
    // Update editor inputs
    const info = getShapeInfo(drag.shape);
    if (document.getElementById('ed-left')) document.getElementById('ed-left').value = info.left.toFixed(3);
    if (document.getElementById('ed-top')) document.getElementById('ed-top').value = info.top.toFixed(3);
    drag = null;
  }
});

// Reset/clear edits
window.resetEdits = function() {
  if (!confirm('Сбросить все правки и перезагрузить?')) return;
  localStorage.removeItem(STORAGE_KEY);
  location.reload();
};
window.exportHTML = function() {
  // Get the current slide's outer HTML
  const html = document.documentElement.outerHTML;
  const blob = new Blob([html], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'index-edited.html';
  a.click();
};

// Initial load
loadEdits();
restoreEdits();

const start = parseInt(location.hash.slice(1), 10);
goto(isNaN(start) ? 1 : start, false);
