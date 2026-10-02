from collections import Counter

from backend.db.session import SessionLocal
from backend.domain.models import WorkOrder
from backend.gateways.factory import create_knowledge_gateway

db = SessionLocal()
query = db.query(WorkOrder).filter(WorkOrder.id == "b5a7fa7f-3f0d-45b4-9953-ccd27b1fd91e").one().content
db.close()

gateway = create_knowledge_gateway()
evidence = gateway.search(
    query,
    ["department_duties", "responsibilities", "regulations", "historical_cases"],
    top_k=8,
)
print("evidence_count", len(evidence))
print(Counter(item.knowledge_base_id for item in evidence))
for item in evidence:
    print(
        item.evidence_id[:44],
        item.knowledge_base_id,
        str(item.document_title or "")[:45],
        round(item.score, 3),
    )
