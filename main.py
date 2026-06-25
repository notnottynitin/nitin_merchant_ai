from fastapi import FastAPI, Response
from datetime import datetime, timezone
import time

app = FastAPI()
START_TIME = time.time()

@app.get("/")
def root():
    return {
        "message": "Nitin Merchant AI is running.",
        "status": "ok"
    }

store = {
    "category": {},
    "merchant": {},
    "customer": {},
    "trigger": {}
}
versions = {}

@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": {
            "category": len(store["category"]),
            "merchant": len(store["merchant"]),
            "customer": len(store["customer"]),
            "trigger": len(store["trigger"])
        }
    }

@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "Nitin_Merchant_AI",
        "team_members": ["Nitin"],
        "model": "rule-based composer",
        "approach": "FastAPI stateful context store with trigger-based message generation",
        "contact_email": "contactnitinforwork@gmail.com",
        "version": "1.0",
        "submitted_at": datetime.now(timezone.utc).isoformat()
    }

@app.post("/v1/context")
def context(data: dict, response: Response):
    scope = data.get("scope")
    context_id = data.get("context_id")
    version = data.get("version", 1)
    payload = data.get("payload", {})

    if scope not in store:
        response.status_code = 400
        return {"accepted": False, "reason": "invalid_scope"}

    old_version = versions.get(context_id, 0)
    if version <= old_version:
        response.status_code = 409
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": old_version
        }

    store[scope][context_id] = payload
    versions[context_id] = version

    return {
        "accepted": True,
        "ack_id": f"ack_{context_id}_v{version}",
        "stored_at": datetime.now(timezone.utc).isoformat()
    }

@app.post("/v1/tick")
def tick(data: dict):
    actions = []

    for trigger_id in data.get("available_triggers", []):
        trigger = store["trigger"].get(trigger_id)
        if not trigger:
            continue

        merchant_id = trigger.get("merchant_id")
        merchant = store["merchant"].get(merchant_id)
        if not merchant:
            continue

        category_slug = merchant.get("category_slug")
        category = store["category"].get(category_slug, {})

        customer = None
        customer_id = trigger.get("customer_id")
        if customer_id:
            customer = store["customer"].get(customer_id)

        msg = compose_message(category, merchant, trigger, customer)

        actions.append({
            "conversation_id": f"conv_{trigger_id}",
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": msg["send_as"],
            "trigger_id": trigger_id,
            "template_name": "vera_template_v1",
            "template_params": [],
            "body": msg["body"],
            "cta": msg["cta"],
            "suppression_key": msg["suppression_key"],
            "rationale": msg["rationale"]
        })

    return {"actions": actions}

@app.post("/v1/reply")
def reply(data: dict):
    message = data.get("message", "").lower()

    auto_reply_phrases = [
        "thank you for contacting",
        "thanks for contacting",
        "we will respond shortly",
        "our team will respond",
        "business account"
    ]

    if any(p in message for p in auto_reply_phrases):
        return {
            "action": "end",
            "rationale": "Detected WhatsApp Business auto-reply and ended to avoid wasted turns"
        }

    if any(p in message for p in ["stop", "spam", "useless", "don't message", "do not message", "not interested"]):
        return {
            "action": "end",
            "rationale": "Merchant declined or was hostile, so conversation ended respectfully"
        }

    if any(p in message for p in ["yes", "ok", "okay", "lets do", "let's do", "send", "do it", "next", "haan"]):
        return {
            "action": "send",
            "body": "Done — I’ll draft it now with your actual offer and business tone. You can review before sending.",
            "cta": "open_ended",
            "rationale": "Merchant committed, so bot moved to action mode instead of asking more qualifying questions"
        }

    return {
        "action": "send",
        "body": "Got it. I can help with a customer WhatsApp, Google post, or offer copy — which one should I draft?",
        "cta": "open_ended",
        "rationale": "Clarifying merchant intent with a low-friction next step"
    }

def compose_message(category, merchant, trigger, customer=None):
    identity = merchant.get("identity", {})
    name = identity.get("name", "your business")
    owner = identity.get("owner_first_name", "")
    performance = merchant.get("performance", {})
    peer = category.get("peer_stats", {})
    offers = merchant.get("offers", [])
    active_offer = next((o.get("title") for o in offers if o.get("status") == "active"), None)
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    suppression_key = trigger.get("suppression_key", trigger.get("id", ""))

    send_as = "merchant_on_behalf" if customer else "vera"

    if kind == "research_digest":
        item_id = payload.get("top_item_id")
        item = find_digest_item(category, item_id)
        body = (
            f"Dr. {owner or name}, {item.get('source', 'this week’s digest')} has one useful update: "
            f"{item.get('title', 'a new category insight')}. "
            f"{item.get('summary', '')[:130]} "
            f"Want me to turn this into a patient-friendly WhatsApp?"
        )
        cta = "YES/STOP"

    elif kind == "regulation_change":
        item = find_digest_item(category, payload.get("top_item_id"))
        deadline = payload.get("deadline_iso", "")
        body = (
            f"{name} team, compliance heads-up: {item.get('title', 'new regulation update')}. "
            f"Deadline: {deadline}. {item.get('actionable', 'Worth checking your SOP once.')} "
            f"Want me to draft a simple checklist?"
        )
        cta = "YES/STOP"

    elif kind == "recall_due" and customer:
        cname = customer.get("identity", {}).get("name", "there")
        slots = payload.get("available_slots", [])
        slot_text = " or ".join([s.get("label", "") for s in slots[:2]]) if slots else "this week"
        offer = active_offer or "Dental Cleaning @ ₹299"
        body = (
            f"Hi {cname}, {name} here. Your {payload.get('service_due', 'follow-up')} is due. "
            f"Available slots: {slot_text}. {offer}. Reply YES to book."
        )
        cta = "YES/STOP"

    elif kind == "perf_dip":
        metric = payload.get("metric", "calls")
        delta = int(payload.get("delta_pct", 0) * 100)
        body = (
            f"{name}, quick alert — your {metric} dropped {abs(delta)}% in the last {payload.get('window', '7d')}. "
            f"Want me to draft one Google post using {active_offer or 'your best offer'} to recover enquiries?"
        )
        cta = "YES/STOP"

    elif kind == "renewal_due":
        days = payload.get("days_remaining", merchant.get("subscription", {}).get("days_remaining"))
        amount = payload.get("renewal_amount", "")
        body = (
            f"{name}, your {payload.get('plan', 'Pro')} plan renewal is due in {days} days"
            f"{f' at ₹{amount}' if amount else ''}. Want me to show what leads/calls came from the last 30 days?"
        )
        cta = "YES/STOP"

    elif kind == "wedding_package_followup" and customer:
        cname = customer.get("identity", {}).get("name", "there")
        body = (
            f"Hi {cname}, {name} here 💍 {payload.get('days_to_wedding')} days to your wedding. "
            f"This is the right window for {payload.get('next_step_window_open', 'bridal prep')}. "
            f"Want us to block your preferred slot?"
        )
        cta = "YES/STOP"

    elif kind == "curious_ask_due":
        body = (
            f"Hi {owner or name}! Quick check — what service has been most asked-for this week at {name}? "
            f"I’ll turn it into a short WhatsApp/Google post."
        )
        cta = "open_ended"

    else:
        views = performance.get("views", "")
        calls = performance.get("calls", "")
        ctr = performance.get("ctr", "")
        peer_ctr = peer.get("avg_ctr", "")
        body = (
            f"{name}, quick growth idea: your 30-day profile has {views} views, {calls} calls, CTR {ctr}. "
            f"Peer CTR is {peer_ctr}. Want me to draft one specific offer post using {active_offer or 'your catalog'}?"
        )
        cta = "YES/STOP"

    return {
        "body": clean(body),
        "cta": cta,
        "send_as": send_as,
        "suppression_key": suppression_key,
        "rationale": f"Composed using trigger kind '{kind}', merchant data, category voice, and available offer/context."
    }

def find_digest_item(category, item_id):
    for item in category.get("digest", []):
        if item.get("id") == item_id:
            return item
    return category.get("digest", [{}])[0] if category.get("digest") else {}

def clean(text):
    return " ".join(str(text).split())