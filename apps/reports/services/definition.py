from django.db import transaction

from ..errors import ReportError
from ..models import ReportField, ReportSection
from ..types import FieldKind


def _invalid(msg):
    return ReportError(msg, "invalid")


def _text(data, key, max_len=100):
    v = data.get(key)
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > max_len:
        raise _invalid(f"A valid {key} is required.")
    return v.strip()


def _order(data, default):
    v = data.get("order", default)
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 32767:
        raise _invalid("Invalid order.")
    return v


def _bool(data, key, default):
    v = data.get(key, default)
    if not isinstance(v, bool):
        raise _invalid(f"Invalid {key}.")
    return v


@transaction.atomic
def save_definition(report_type, sections: list) -> None:
    if not isinstance(sections, list):
        raise _invalid("Sections must be a list.")
    existing_sections = {str(s.uuid): s for s in report_type.sections.all()}
    existing_fields = {str(f.uuid): f for f in ReportField.objects.filter(
        section__report_type=report_type)}
    kept_sections, kept_fields = set(), set()

    for s_i, s_data in enumerate(sections):
        if not isinstance(s_data, dict):
            raise _invalid("Invalid section.")
        s_uuid = s_data.get("uuid")
        name = _text(s_data, "name")
        order = _order(s_data, s_i)
        active = _bool(s_data, "is_active", True)
        if s_uuid:
            section = existing_sections.get(str(s_uuid))
            if section is None:
                raise _invalid("Unknown section.")
            section.name, section.order, section.is_active = name, order, active
            section.save()
        else:
            section = ReportSection.objects.create(
                report_type=report_type, name=name, order=order, is_active=active)
        kept_sections.add(str(section.uuid))

        for f_i, f_data in enumerate(s_data.get("fields") or []):
            if not isinstance(f_data, dict):
                raise _invalid("Invalid field.")
            label = _text(f_data, "label")
            kind = f_data.get("kind")
            if kind not in FieldKind.values:
                raise _invalid("Invalid field kind.")
            required = _bool(f_data, "required", False)
            f_order = _order(f_data, f_i)
            f_active = _bool(f_data, "is_active", True)
            f_uuid = f_data.get("uuid")
            if f_uuid:
                field = existing_fields.get(str(f_uuid))
                if field is None:
                    raise _invalid("Unknown field.")
                if kind != field.kind and field.values.exists():
                    raise ReportError(
                        "A field with submitted values cannot change kind.", "kind_locked",
                        {str(field.uuid): "A field with submitted values cannot change kind."})
                field.section = section
                field.label, field.kind, field.required = label, kind, required
                field.order, field.is_active = f_order, f_active
                field.save()
            else:
                field = ReportField.objects.create(
                    section=section, label=label, kind=kind, required=required,
                    order=f_order, is_active=f_active)
            kept_fields.add(str(field.uuid))

    for key, field in existing_fields.items():
        if key in kept_fields:
            continue
        if field.values.exists():
            if field.is_active:
                field.is_active = False
                field.save(update_fields=["is_active", "updated_at"])
        else:
            field.delete()
    for key, section in existing_sections.items():
        if key in kept_sections:
            continue
        if ReportField.objects.filter(section=section, values__isnull=False).exists():
            if section.is_active:
                section.is_active = False
                section.save(update_fields=["is_active", "updated_at"])
        else:
            section.delete()
