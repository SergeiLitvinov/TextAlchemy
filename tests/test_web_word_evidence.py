"""Real Word evidence, actual Web conversion and Chromium history/reload."""

import json
import os
import shutil
import subprocess
import sys

import httpx
import pytest
from playwright.sync_api import expect

from tests import test_browser_e2e as fixtures
from tests.test_word_acceptance import SCRIPT, fixture_document
from textalchemy.web.queue import task_queue

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store


@pytest.mark.skipif(sys.platform != "win32" or os.getenv("TEXTALCHEMY_WORD_ACCEPTANCE") != "1",
                    reason="Requires installed Word and explicit local acceptance run")
@pytest.mark.parametrize("width", [375, 1280])
def test_real_word_checks_survive_browser_reload_and_preserve_heading(e2e_server, page, task_store, tmp_path, width):
    from axe_core_python.sync_playwright import Axe

    source = fixture_document()
    marker = "Editable body"
    page.set_viewport_size({"width": width, "height": 900})
    with httpx.Client(base_url=e2e_server, timeout=60) as client:
        for cycle in range(1, 3):
            imported = client.post("/api/convert", files={"file": ("source.docx", source)},
                                   data={"target_format": "model"})
            assert imported.status_code == 200, imported.text
            assert task_queue.wait_idle(timeout=30)
            model = client.get(imported.json()["result"])
            assert model.status_code == 200
            batch = client.post("/api/convert/batch", files=[("files", ("own-model.json", model.content))],
                                data={"target_format": "docx"})
            assert batch.status_code == 200, batch.text
            assert task_queue.wait_idle(timeout=30)
            created = batch.json()
            task_id = created["tasks"][0]["task_id"]
            task = task_store.get(task_id)
            assert task["status"] == "done"
            result = client.get(f"/api/convert/result/{task_id}")
            native, edited = tmp_path / f"cycle-{cycle}.docx", tmp_path / f"edited-{cycle}.docx"
            native.write_bytes(result.content)
            replacement = f"Edited cycle {cycle}"
            completed = subprocess.run([
                shutil.which("pwsh") or "powershell", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                "-InputPath", str(native), "-OutputPath", str(edited), "-FindText", marker, "-Replacement", replacement,
            ], capture_output=True, encoding="utf-8", check=True, timeout=90)
            record = json.loads(completed.stdout)
            assert record["checks"]["heading_outline"] is True
            assert task_store.store_target_program_check(task_id, expected=task, evidence=record)
            for _ in range(2):
                page.goto(e2e_server + "/convert")
                fixtures._wait_convert_ready(page)
                page.locator("#conversionHistory > summary").click()
                job = page.locator(f'#historyList details[data-job="{created["job_id"]}"]')
                job.locator("summary").click()
                job.locator(f'[data-preview-task="{task_id}"]').click()
                section = page.locator("#targetProgramChecks")
                expect(section).to_be_visible(timeout=30000)
                expect(section).to_contain_text("Автоматизированная проверка Word (COM)")
                expect(section).to_contain_text("Правка текста: подтверждено")
                expect(section).to_contain_text("Правка ячейки: подтверждено")
                expect(section).to_contain_text("Уровень заголовка: подтверждено")
                expect(section).to_contain_text("Наблюдаемый уровень: 2")
                expect(page.locator("#qualityBadge")).not_to_have_text("Есть замечания проверки Word")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert task_store.get(task_id) == task
            violations = Axe().run(page)["violations"]
            assert not [item for item in violations if item["impact"] in {"critical", "serious"}], violations
            source, marker = edited.read_bytes(), replacement
    page.screenshot(path=str(tmp_path / f"word-evidence-{width}.png"), full_page=True)
    assert page.e2e_errors == []


@pytest.mark.parametrize("heading", [False, None])
def test_contract_display_does_not_promote_failed_or_unknown_heading(e2e_server, page, heading):
    """A labelled display double verifies UI states; it is not native Word evidence."""
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.evaluate("""async (heading) => {
        const {renderTargetChecks} = await import('/static/js/pages/convert/target-checks.js');
        const record = {program: {name: 'Контрактный пример', version: 'display-test', build: 'fixture'},
            checks: {heading_outline: heading}, scope: ['heading_outline'], observations: {},
            artifact_sha256: '0'.repeat(64), edited_sha256: '1'.repeat(64)};
        document.getElementById('resultCard').hidden = false;
        document.getElementById('qualityBadge').textContent = 'Результат конвертации';
        renderTargetChecks(id => document.getElementById(id),
            {success: true, metrics: {target_program_checks: [record]}});
    }""", heading)
    section = page.locator("#targetProgramChecks")
    expect(section).to_be_visible()
    expect(section).to_contain_text("Контрактный пример")
    expect(section).to_contain_text("Уровень заголовка: " + ("не прошло" if heading is False else "не проверено"))
    expect(section).not_to_contain_text("Уровень заголовка: подтверждено")
    if heading is False:
        expect(page.locator("#qualityBadge")).to_have_text("Есть замечания проверки Word")
        expect(section.locator('.target-check-failed')).to_have_count(1)
    else:
        expect(page.locator("#qualityBadge")).to_have_text("Результат конвертации")
        expect(section.locator('.target-check-failed')).to_have_count(0)
    assert page.e2e_errors == []
