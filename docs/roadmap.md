# Roadmap

## Cut on purpose (and why)

These were left out to keep the artifact focused on the part that matters —
matching + AI extraction. Each is a deliberate scope decision, not an oversight.

| Cut                       | Why                                                        |
|---------------------------|------------------------------------------------------------|
| Real SMS/email sending    | Adds Twilio/email infra and compliance, not core to the demo. Messages are generated and shown, not sent. |
| Auth / multi-user         | Single-operator demo. Auth is well-understood plumbing that adds no signal. |
| Real investor data        | Synthetic seed mirrors real buy box shapes. Engine is data-source agnostic. |
| Full pipeline kanban      | The interesting problem is matching, not drag-and-drop stage tracking. |
| Skip tracing / enrichment | Out of scope; would depend on third-party data vendors.    |

## Next steps (if this continued)

### 1. Learned scoring from outcomes
Replace fixed weights with a model trained on closed-deal data: which buyer
actually bought, at what price, how fast. Start by logging match → outcome,
then fit a simple model and compare against the rule-based baseline. Keep the
rule-based scorer as an explainable fallback.

### 2. Real outreach
Wire the message stub to Twilio (SMS) and an email provider. Add send
scheduling, delivery tracking, and reply capture.

### 3. Reply classification
Auto-tag incoming buyer replies (interested / pass / wants details / price
question) so follow-up can be prioritized.

### 4. Buy box from conversation history
Extract and update a buyer's buy box from a full thread, not just one message —
buyers reveal criteria over time.

### 5. Confidence on extraction
Have the extractor flag low-confidence fields so a human can confirm before the
buy box is trusted in matching.

## Known limitations

- Extraction quality depends on the AI model and prompt; ambiguous messages may
  produce partial buy boxes.
- Market matching is exact-string on city; real systems need metro/zip/radius
  geography.
- Scoring weights are hand-tuned, not validated against real conversion data.
