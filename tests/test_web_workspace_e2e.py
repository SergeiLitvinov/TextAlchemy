"""Пользовательские переходы между заполнением, редактором и конструктором."""
import re

import pytest

from tests import test_browser_e2e as fixtures

browser, e2e_server, page = fixtures.browser, fixtures.e2e_server, fixtures.page


@pytest.mark.parametrize('width', [375, 1280])
def test_generator_modes_preserve_input(e2e_server, page, width):
    from playwright.sync_api import expect

    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/generate')
    fixtures._generator_step(page)
    expect(page.locator('#field-title')).to_be_visible()
    expect(page.locator('#templateEditor')).to_be_hidden()
    expect(page.locator('#datasetName')).to_be_hidden()
    page.locator('#field-body').fill('Первый абзац\nВторой абзац')
    page.locator('#editMode').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#documentFields')).to_be_hidden()
    expect(page.locator('#documentOutput')).to_be_hidden()
    page.get_by_text('Изменить переменную шаблона', exact=True).click()
    expect(page.locator('#variableInspect')).to_be_visible()
    page.get_by_text('Повторять строку таблицы', exact=True).click()
    expect(page.locator('#variableInspect')).to_be_hidden()
    expect(page.locator('#rowLoopInspect')).to_be_visible()
    page.locator('#fillMode').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#field-body')).to_have_value('Первый абзац\nВторой абзац')
    page.reload()
    fixtures._generator_step(page)
    page.locator('#restoreDraft').click()
    expect(page.locator('#field-body')).to_have_value('Первый абзац\nВторой абзац')
    if width == 375:
        assert page.locator('#documentFields').bounding_box()['y'] < page.locator('#previewSection').bounding_box()['y']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.e2e_errors == []


@pytest.mark.parametrize('width', [375, 1280])
def test_pipeline_search_keeps_operation_ids(e2e_server, page, width):
    from playwright.sync_api import expect

    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/pipeline')
    expect(page.locator('#stepsList .step-card')).to_have_count(3)
    expect(page.locator('#stepsList .op-select').first).to_contain_text('Открыть файл')
    if not page.locator('#operationCatalog').evaluate('el => el.open'):
        page.locator('#operationCatalog > summary').click()
    page.locator('#opSearch').fill('Сохранить документ в Word')
    result = page.locator('#opsPalette [data-op="render.docx_model"]')
    expect(result).to_be_visible()
    result.click()
    expect(page.locator('#stepsList .step-card')).to_have_count(4)
    page.locator('#modeExpertBtn').click()
    expect(page.locator('#specText')).to_have_value(re.compile('render.docx_model'))
    page.locator('#modeVisualBtn').click()
    expect(page.locator('#stepsList .step-card')).to_have_count(4)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.e2e_errors == []


def test_editor_accessibility(e2e_server, page):
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    for route in ('generate', 'pdf-order'):
        page.goto(f'{e2e_server}/{route}')
        if route == 'generate':
            fixtures._generator_step(page)
            expect(page.locator('#field-title')).to_be_visible()
            page.locator('#editMode').click()
            page.get_by_text('Настроить условный абзац', exact=True).click()
        result = Axe().run(page)
        serious = [(v['id'], [n['html'] for n in v['nodes']]) for v in result['violations']
                   if v.get('impact') in ('serious', 'critical')]
        assert not serious, serious


@pytest.mark.parametrize('width', [375, 1280])
def test_pipeline_connections_and_renaming(e2e_server, page, width):
    from playwright.sync_api import expect

    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/pipeline')
    expect(page.locator('#stepsList .step-card')).to_have_count(3)
    expect(page.locator('#input-0 option')).to_have_count(1)
    expect(page.locator('#input-1 option')).to_have_count(2)
    page.locator('#output-0').fill('source')
    if not page.locator('#operationCatalog').evaluate('el => el.open'):
        page.locator('#operationCatalog > summary').click()
    page.locator('#opSearch').click()  # Commit the changed source name.
    expect(page.locator('#connection-1')).to_contain_text('Источник удалён')
    expect(page.locator('#input-1')).to_have_value('doc')
    page.locator('#input-1').select_option('source')
    expect(page.locator('#connection-1')).not_to_contain_text('Источник удалён')
    if not page.locator('#operationCatalog').evaluate('el => el.open'):
        page.locator('#operationCatalog > summary').click()
    page.locator('#opSearch').fill('render.latex.pandoc')
    if not page.locator('#operationCatalog').evaluate('el => el.open'):
        page.locator('#operationCatalog > summary').click()
    page.locator('[data-op="render.latex.pandoc"]').click()
    if not page.locator('#operationCatalog').evaluate('el => el.open'):
        page.locator('#operationCatalog > summary').click()
    page.locator('[data-op="render.latex.pandoc"]').click()
    expect(page.locator('#output-3')).to_have_value('result_4')
    expect(page.locator('#output-4')).to_have_value('result_5')
    page.locator('#stepsList .step-card').nth(1).locator('[data-move="-1"]').click()
    expect(page.locator('#connection-0')).to_contain_text('Источник удалён')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.e2e_errors == []


@pytest.mark.parametrize('width', [375, 1280])
def test_pipeline_result_in_both_modes(e2e_server, page, width):
    from playwright.sync_api import expect

    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/pipeline')
    expect(page.locator('#stepsList .step-card')).to_have_count(3)
    page.locator('#modeExpertBtn').click()
    page.locator('#specText').fill('steps:\n  - op: ingest.file\n    params: {path: missing-workspace-test.txt}')
    page.locator('#expertRunBtn').click()
    expect(page.locator('#pipeline-result-title')).to_have_text('Сценарий не выполнен')
    expect(page.locator('#resultSteps')).to_contain_text('ошибка')
    expect(page.locator('#result-output')).to_be_hidden()
    page.locator('#specText').fill('steps:\n  - op: render.json\n    params: {items: []}\n    output: bibliography')
    page.locator('#modeVisualBtn').click()
    expect(page.locator('#stepsList .step-card')).to_have_count(1)
    expect(page.locator('#output-0')).to_have_value('bibliography')
    page.locator('#runBtn').click()
    expect(page.locator('#pipeline-result-title')).to_have_text('Сценарий выполнен')
    expect(page.locator('#resultValue')).to_have_text('[]')
    expect(page.locator('#resultSteps')).not_to_contain_text('ошибка')
    page.get_by_text('Подробный отчёт (JSON)', exact=True).click()
    expect(page.locator('#result-output')).to_contain_text('"ok": true')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.e2e_errors == []


@pytest.mark.parametrize('width', [375, 1280])
def test_pdf_preparation_is_conversion_step(e2e_server, page, tmp_path, width):
    from playwright.sync_api import expect

    pdf = fixtures._make_pdf(tmp_path / 'prepare.pdf', 'Prepare for conversion')
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/convert')
    fixtures._wait_convert_ready(page)
    expect(page.locator('nav a[href="/pdf-order"]')).to_have_count(0)
    expect(page.locator('#pdfPreparation')).to_be_hidden()
    page.locator('#fileInput').set_input_files(str(pdf))
    page.locator('#pdfPreparation > summary').click()
    expect(page.locator('#preparePdfBtn')).to_be_visible()
    page.locator('#preparePdfBtn').click()
    page.wait_for_url('**/pdf-order?draft=*')
    expect(page.get_by_role('heading', name='Подготовка PDF к конвертации')).to_be_visible()
    expect(page.locator('#orderEditor')).to_be_visible()
    expect(page.locator('#orderBlocks')).to_contain_text('Prepare for conversion')
    expect(page.locator('nav a[href="/convert"]')).to_have_attribute('aria-current', 'page')
    expect(page.get_by_text('Исходный PDF остаётся без изменений.', exact=False)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.e2e_errors == []
