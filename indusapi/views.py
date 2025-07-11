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
    
    
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import json
from .status_api import scrape_po_status

@csrf_exempt
@require_POST
def bulk_scrape(request):
    try:
       
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"response": "error", "message": "Invalid JSON payload"}, status=400)

        
        if not isinstance(body, dict):
            return JsonResponse({"response": "error", "message": "Request body must be a JSON object"}, status=400)

        po_numbers = body.get("po_numbers", [])
        if not isinstance(po_numbers, list):
            return JsonResponse({"response": "error", "message": "'po_numbers' must be a list"}, status=400)

        if not po_numbers:
            return JsonResponse({"response": "error", "message": "No PO numbers provided"}, status=400)

        
        result = scrape_po_status()

        
        if not isinstance(result, dict):
            return JsonResponse({"response": "error", "message": "Invalid scraper response format"}, status=500)

        if result.get("status") == "error":
            return JsonResponse({"response": "error", "message": result.get("message", "Scraping failed")}, status=500)

      
        records = result.get("records", [])
        if not isinstance(records, list):
            return JsonResponse({"response": "error", "message": "Invalid records format in scraper response"}, status=500)

        record_map = {rec["po_number"]: rec["status"] for rec in records if isinstance(rec, dict)}
        response = {f"po number:{po}": f"status:{record_map.get(po, 'Not found')}" for po in po_numbers}
        return JsonResponse({"response": response}, status=200)

    except Exception as e:
        return JsonResponse({"response": "error", "message": f"Server error: {str(e)}"}, status=500)

def health_check(request):
    return JsonResponse({"response": "success", "message": "API is running"}, status=200)