"""Real documentation navigation, local search and responsive theme checks."""

import functools
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests import test_browser_e2e as browser_fixtures
from tools.documentation.generated import ROOT

browser, page = browser_fixtures.browser, browser_fixtures.page


@pytest.fixture(scope='module')
def docs_server():
    subprocess.run([sys.executable, '-m', 'tools.docs', 'build'], cwd=ROOT, check=True, capture_output=True)

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    handler = functools.partial(QuietHandler, directory=str(ROOT / '.textalchemy/docs-site'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize('width', [375, 1280])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_documentation_read_search_and_navigate(docs_server, page, width, theme):
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    page.set_viewport_size({'width': width, 'height': 900})
    page.emulate_media(color_scheme=theme)
    page.goto(docs_server)
    expect(page.locator('#hero-title')).to_contain_text('TextAlchemy')
    expect(page.locator('html')).to_have_attribute('data-theme', theme)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not [v for v in Axe().run(page)['violations'] if v.get('impact') in ('serious', 'critical')]

    page.locator('[data-open-search]').click()
    expect(page.locator('#mkdocs-search-query')).to_be_focused()
    page.locator('#mkdocs-search-query').fill('конвертация')
    page.locator('#mkdocs-search-query').press('ArrowRight')
    expect(page.locator('#mkdocs-search-results article').first).to_be_visible(timeout=30000)
    page.locator('#mkdocs-search-query').press('Escape')
    expect(page.locator('#docs-search')).not_to_be_visible()
    expect(page.locator('[data-open-search]')).to_be_focused()

    page.get_by_role('link', name='Начать работу', exact=False).click()
    expect(page.locator('.docs-prose h1')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('html')).to_have_attribute('data-theme', theme)
    if width == 375:
        menu = page.locator('.docs-menu-button')
        menu.click()
        expect(menu).to_have_attribute('aria-expanded', 'true')
        expect(page.locator('#docs-navigation')).to_be_visible()
        page.locator('#docs-navigation summary').filter(has_text='Разработка').click()
        page.locator('#docs-navigation').get_by_role('link', name='Навигатор по коду', exact=True).click()
    else:
        expect(page.locator('.docs-outline')).to_be_visible()
        page.locator('.docs-top-nav').get_by_role('link', name='Код', exact=True).click()
    expect(page.locator('.docs-prose h1')).to_contain_text('Навигатор')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not [v for v in Axe().run(page)['violations'] if v.get('impact') in ('serious', 'critical')]
    page.locator('.docs-theme-button').click()
    other = 'dark' if theme == 'light' else 'light'
    expect(page.locator('html')).to_have_attribute('data-theme', other)
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme', other)
    assert page.e2e_errors == []
