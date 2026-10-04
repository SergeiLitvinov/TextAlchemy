"""Recognise historical application resource labels and delegate native assembly."""

from opendoc import DocumentModel
from opendoc_formats.package_resources import assemble_docx_package_resources

LEGACY_ROLES = {
    "docx-footnotes": "footnotes",
    "docx-endnotes": "endnotes",
    "docx-numbering": "numbering",
    "docx-styles": "styles",
    "docx-theme": "theme",
}


def migrate_legacy_ooxml_resources(document: DocumentModel) -> DocumentModel:
    """Only the application recognises its historical JSON/version/resource labels."""
    if document.package is not None:
        return document
    roles = {
        resource_id: LEGACY_ROLES[str(resource.properties.get("role") or resource_id)]
        for resource_id, resource in document.resources.items()
        if str(resource.properties.get("role") or resource_id) in LEGACY_ROLES and resource.data is not None
    }
    return assemble_docx_package_resources(document, roles, consume_resources=True) if roles else document
