from supplymesh.cards.renderer import CardEnvelope, render_card
from supplymesh.domain.procurement import PurchaseOrder


def purchase_order_detail(po: PurchaseOrder, *, require_send_approval: bool = True) -> CardEnvelope:
    payload: dict[str, object] = {
        "title": f"Purchase order {po.po_number}",
        "target": {"id": str(po.po_id), "version": po.version},
        "supplier_id": po.supplier_id,
        "currency": po.currency,
        "total": str(po.total),
        "lines": [line.model_dump(mode="json") for line in po.lines],
    }
    if require_send_approval:
        payload["actions"] = [
            {
                "label": "Approve and send",
                "style": "primary",
                "value": {
                    "action": "approve_and_send_purchase_orders",
                    "target_id": str(po.po_id),
                    "target_version": po.version,
                },
            },
            {
                "label": "Cancel",
                "value": {
                    "action": "cancel",
                    "target_id": str(po.po_id),
                    "target_version": po.version,
                },
            },
        ]
    return render_card("review", payload)


def counterproposal_form(*, po_id: str, po_version: int) -> CardEnvelope:
    return render_card(
        "form",
        {
            "title": "Supplier counterproposal",
            "target": {"id": po_id, "version": po_version},
            "fields": [
                {"id": "quantity", "label": "Acceptable quantity", "type": "number"},
                {"id": "maximum_price", "label": "Maximum unit price", "type": "number"},
                {"id": "required_date", "label": "Required date", "type": "date"},
                {"id": "note", "label": "Note", "type": "text"},
            ],
            "submit": {
                "label": "Review counterproposal",
                "action": "review_counterproposal",
            },
        },
    )
