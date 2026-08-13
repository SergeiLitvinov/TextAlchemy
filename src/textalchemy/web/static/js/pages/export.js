"use strict";

const status = document.getElementById('status');

document.querySelectorAll('a[data-fmt]').forEach((link) => {
    link.addEventListener('click', () => {
        const format = link.dataset.fmt;
        toast(`Готовим ${format}`, 'info');
        status.hidden = false;
        status.className = 'status-bar info';
        status.textContent = `Файл ${format} будет сохранён в загрузки браузера.`;
        setTimeout(() => { status.hidden = true; }, 2500);
    });
});
