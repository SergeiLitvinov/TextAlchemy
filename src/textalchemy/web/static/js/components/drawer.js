"use strict";

// Выдвижные панели открываются по одной и удерживают фокус внутри.
let activeDrawer = null;
const focusable = 'a[href], button, input, select, textarea, summary, [tabindex]';

export function createDrawer({panel, triggers, closeTargets, background, onChange, initialFocus, fallbackFocus}) {
    let opened = false, returnFocus = null, previousInert = [];
    function close(restoreFocus = true) {
        if (!opened) return;
        opened = false;
        previousInert.forEach(([element, value]) => { element.inert = value; });
        previousInert = [];
        triggers.forEach(trigger => trigger.setAttribute('aria-expanded', 'false'));
        onChange(false);
        panel.removeAttribute('aria-modal');
        panel.removeAttribute('role');
        if (activeDrawer === controller) activeDrawer = null;
        if (restoreFocus) {
            const target = returnFocus?.isConnected && !returnFocus.closest('[inert]') ? returnFocus : fallbackFocus?.();
            target?.focus();
        }
    }
    function open() {
        if (opened) return;
        const origin = document.activeElement;
        activeDrawer?.close(false);
        returnFocus = origin;
        opened = true;
        activeDrawer = controller;
        previousInert = background.filter(Boolean).map(element => [element, element.inert]);
        previousInert.forEach(([element]) => { element.inert = true; });
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-modal', 'true');
        triggers.forEach(trigger => trigger.setAttribute('aria-expanded', 'true'));
        onChange(true);
        (initialFocus?.() || panel.querySelector(focusable) || panel).focus();
    }
    const controller = {open, close, isOpen: () => opened};
    triggers.forEach(trigger => trigger.addEventListener('click', () => opened ? close() : open()));
    closeTargets.forEach(target => target.addEventListener('click', () => close()));
    document.addEventListener('keydown', event => {
        if (!opened || document.querySelector('dialog[open]')) return;
        if (event.key === 'Escape') { event.preventDefault(); close(); return; }
        if (event.key !== 'Tab') return;
        const controls = [...panel.querySelectorAll(focusable)].filter(element =>
            !element.disabled && element.tabIndex >= 0 && !element.closest('[inert]') && element.getClientRects().length);
        const first = controls[0] || panel, last = controls.at(-1) || panel;
        if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
            event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
            event.preventDefault(); first.focus();
        }
    });
    return controller;
}
