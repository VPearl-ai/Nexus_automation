# indus_api/views.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
import os, json
from redis import Redis
from dotenv import load_dotenv

load_dotenv()
redis_client = Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    db=int(os.getenv("REDIS_DB"))
)

@api_view(['GET'])
def get_po_data(request):
    data = redis_client.get("indus_latest_data")
    if data:
        records = json.loads(data)
        return Response({
            "status": "success",
            "records": len(records),
            "data": records
        })
    return Response({
        "status": "error",
        "message": "No data available. Please try again later."
    })
