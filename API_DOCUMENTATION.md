# Run-Template API Documentation

## Overview

The `/api/v1/run-template` API allows automated creation and execution of mock scenarios from saved templates. Perfect for CI/CD pipelines, automated testing, and bulk test data generation.

**Endpoint:** `POST /api/v1/run-template/{template_id}`

---

## Quick Start

### Simple Request (Minimum)

```bash
curl -X POST http://localhost:8001/api/v1/run-template/abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "environment": "dev"
  }'
```

### Full Request (All Options)

```bash
curl -X POST http://localhost:8001/api/v1/run-template/abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "environment": "dev",
    "check_in": "2026-07-29",
    "check_out": "2026-07-30",
    "hotel_id": "123456",
    "delete_mock_api_key": true,
    "assign_api_key_to_br": true,
    "force_cleanup": true,
    "timeout_seconds": 300,
    "include_logs": false
  }'
```

---

## Request Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `environment` | string | "dev" | Target environment: "dev" or "stg" |
| `check_in` | string | Today | Check-in date (YYYY-MM-DD) |
| `check_out` | string | Tomorrow | Check-out date (YYYY-MM-DD) |
| `hotel_id` | string | From template | Override template hotel ID |
| `delete_mock_api_key` | boolean | true | Delete all mocks after run |
| `assign_api_key_to_br` | boolean | true | Assign API key to BR |
| `force_cleanup` | boolean | true | Cleanup even if error occurs |
| `timeout_seconds` | integer | 300 | Max wait time for scenario |
| `include_logs` | boolean | false | Include execution logs in response |

### Parameter Details

#### `environment`
- **dev**: Development environment
- **stg**: Staging environment
- Must match where template was created

#### `check_in` / `check_out`
- Format: `YYYY-MM-DD`
- If not provided, uses today/tomorrow
- Example: `"check_in": "2026-07-29"`

#### `delete_mock_api_key`
- **true**: Full cleanup - deletes scenario, mocks, contracts, API key
  - Use for automation tests
  - Saves database space
  - Data unavailable after run
- **false**: Keep everything running
  - Use for debugging
  - Can inspect scenario later
  - Must manually delete later

#### `force_cleanup`
- **true**: Cleanup even if scenario run fails
  - Prevents orphaned scenarios
  - Recommended for automation
- **false**: Skip cleanup on error
  - Helps debug failures
  - Scenario remains for inspection

#### `timeout_seconds`
- Maximum seconds to wait for scenario
- Default: 300 (5 minutes)
- Scenario creation can take 10-30s
- Scenario run can take 10-60s
- Set higher for slow scenarios

#### `include_logs`
- **false** (default): Response excludes logs (smaller)
- **true**: Response includes full execution logs
  - Helpful for debugging failures
  - Response will be larger

---

## Response Format

### Success Response (200)

```json
{
  "request_id": "req-1722181440-a7f2b9c1",
  "status": "COMPLETED",
  
  "scenario_id": "scenario-xyz789",
  "api_key": "api-key-generated-123",
  "api_key_id": "api-key-id-456",
  "contract_id": "contract-c1",
  "search_id": "sid-search123",
  "package_id": "pid-package456",
  
  "check_in": "2026-07-29",
  "check_out": "2026-07-30",
  "hotel_id": "123456",
  
  "deleted": true,
  "assigned_to_br": true,
  
  "steps": {
    "scenario_creation": {
      "status": "SUCCESS",
      "duration_ms": 1200,
      "error": null
    },
    "scenario_run": {
      "status": "SUCCESS",
      "duration_ms": 3400,
      "error": null
    },
    "cleanup": {
      "status": "SUCCESS",
      "duration_ms": 500,
      "error": null
    }
  },
  
  "summary": {
    "total_duration_ms": 5100,
    "all_steps_successful": true,
    "mocks_cleaned_up": true,
    "steps_completed": 3
  },
  
  "error": null,
  "logs": null
}
```

### Error Response (400/500)

```json
{
  "request_id": "req-1722181440-a7f2b9c1",
  "status": "FAILED",
  
  "scenario_id": null,
  "api_key": null,
  
  "error": {
    "code": "TEMPLATE_NOT_FOUND",
    "message": "Template abc123 not found",
    "step_failed": "scenario_creation",
    "details": null
  },
  
  "steps": {
    "scenario_creation": {
      "status": "FAILED",
      "duration_ms": 45,
      "error": "Template not found"
    },
    "scenario_run": {
      "status": "UNKNOWN",
      "duration_ms": 0,
      "error": null
    },
    "cleanup": null
  },
  
  "summary": {
    "total_duration_ms": 150,
    "all_steps_successful": false,
    "mocks_cleaned_up": false,
    "steps_completed": 1
  },
  
  "logs": []
}
```

### Timeout Response (408)

```json
{
  "request_id": "req-1722181440-a7f2b9c1",
  "status": "TIMEOUT",
  
  "error": {
    "code": "SCENARIO_CREATION_TIMEOUT",
    "message": "Scenario creation exceeded 300s",
    "step_failed": "scenario_creation"
  }
}
```

---

## Response Fields Explained

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string | Unique request identifier - use for tracing |
| `status` | string | COMPLETED, FAILED, TIMEOUT |
| `scenario_id` | string | Created scenario ID (or null if failed) |
| `api_key` | string | Generated API key for scenario |
| `api_key_id` | string | API key ID for reference |
| `contract_id` | string | Created contract ID |
| `search_id` | string | Search ID from scenario |
| `package_id` | string | Package ID from scenario |
| `check_in` / `check_out` | string | Dates used in scenario |
| `hotel_id` | string | Hotel ID used |
| `deleted` | boolean | Whether mocks were deleted |
| `assigned_to_br` | boolean | Whether key was assigned to BR |
| `steps` | object | Execution steps with timing |
| `summary` | object | Overall execution summary |
| `error` | object | Error details if failed |
| `logs` | array | Execution logs (if requested) |

---

## Error Codes

| Code | HTTP Status | Meaning | Action |
|------|-------------|---------|--------|
| `TEMPLATE_NOT_FOUND` | 404 | Template ID doesn't exist | Verify template_id is correct |
| `SCENARIO_CREATION_TIMEOUT` | 408 | Scenario took too long to create | Increase timeout_seconds |
| `SCENARIO_CREATION_FAILED` | 500 | Scenario creation errored | Check error details, retry |
| `SCENARIO_RUN_FAILED` | 500 | Running scenario against core app failed | Check core app logs |
| `INTERNAL_ERROR` | 500 | Unexpected error | Check request format, retry |

---

## Usage Examples

### Java/Spring Boot Example

```java
import org.springframework.web.client.RestTemplate;
import org.springframework.http.ResponseEntity;

public class MockScenarioCreator {
    
    private RestTemplate restTemplate = new RestTemplate();
    private String apiUrl = "http://localhost:8001";
    
    public void createAndRunTestData() {
        String templateId = "my-template-123";
        
        RunTemplateRequest request = new RunTemplateRequest(
            environment: "dev",
            check_in: "2026-07-29",
            check_out: "2026-07-30",
            hotel_id: "456789",
            delete_mock_api_key: true,
            assign_api_key_to_br: true,
            force_cleanup: true,
            timeout_seconds: 300,
            include_logs: false
        );
        
        ResponseEntity<RunTemplateResponse> response = restTemplate.postForEntity(
            apiUrl + "/api/v1/run-template/" + templateId,
            request,
            RunTemplateResponse.class
        );
        
        if (response.getStatusCode().is2xxSuccessful()) {
            RunTemplateResponse result = response.getBody();
            String apiKey = result.getApiKey();
            String scenarioId = result.getScenarioId();
            
            System.out.println("Scenario created: " + scenarioId);
            System.out.println("API Key: " + apiKey);
            System.out.println("Total time: " + result.getSummary().getTotalDurationMs() + "ms");
            
            // Now use apiKey for your tests...
        } else {
            System.err.println("Failed: " + response.getBody().getError().getMessage());
        }
    }
}
```

### cURL with Jq (Parse Response)

```bash
# Create scenario and extract API key
API_KEY=$(curl -s -X POST http://localhost:8001/api/v1/run-template/abc123 \
  -H "Content-Type: application/json" \
  -d '{"environment":"dev"}' | jq -r '.api_key')

echo "Generated API Key: $API_KEY"

# Use the key in your tests
curl -X GET http://core-app:8080/search \
  -H "X-API-Key: $API_KEY"
```

### Python Example

```python
import requests
import json

def create_test_scenario():
    url = "http://localhost:8001/api/v1/run-template/abc123"
    
    payload = {
        "environment": "dev",
        "check_in": "2026-07-29",
        "check_out": "2026-07-30",
        "delete_mock_api_key": True,
        "force_cleanup": True,
        "timeout_seconds": 300,
        "include_logs": False
    }
    
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        api_key = result['api_key']
        scenario_id = result['scenario_id']
        
        print(f"✓ Scenario created: {scenario_id}")
        print(f"✓ API Key: {api_key}")
        print(f"✓ Duration: {result['summary']['total_duration_ms']}ms")
        
        return api_key
    else:
        error = response.json()['error']
        print(f"✗ Failed: {error['message']}")
        return None
```

---

## Tracing with Request ID

The `request_id` appears in all backend logs. Use it to trace a single request through the entire system:

```bash
# Get response
RESPONSE=$(curl -s -X POST http://localhost:8001/api/v1/run-template/abc123)
REQUEST_ID=$(echo $RESPONSE | jq -r '.request_id')

echo "Request ID: $REQUEST_ID"

# Search backend logs for this request
grep "$REQUEST_ID" backend.log
# Output:
# [req-1722181440-a7f2b9c1] Starting run-template request
# [req-1722181440-a7f2b9c1] Loaded template: My Template
# [req-1722181440-a7f2b9c1] Generated namespace: abc123-a7f2b9c1
# [req-1722181440-a7f2b9c1] Scenario created: scenario-xyz
# [req-1722181440-a7f2b9c1] Scenario run completed: SUCCESS
# [req-1722181440-a7f2b9c1] Cleanup successful
# [req-1722181440-a7f2b9c1] Run-template completed successfully
```

---

## Best Practices for Automation

### ✅ Do:
- Use `delete_mock_api_key: true` to cleanup after tests
- Set `timeout_seconds` based on expected scenario time
- Use `force_cleanup: true` to prevent orphaned scenarios
- Store request_id for debugging failures
- Run templates in sequence, not parallel (to avoid namespace conflicts)

### ❌ Don't:
- Leave `delete_mock_api_key: false` in production (data bloat)
- Use very short timeout_seconds (will timeout)
- Use invalid template_id (will fail immediately)
- Ignore error responses (may indicate issues)
- Log API keys in plain text

---

## Performance Characteristics

| Operation | Typical Time | Max Time |
|-----------|--------------|----------|
| Scenario creation | 10-30s | 60s |
| Scenario run | 10-60s | 120s |
| Cleanup | 1-5s | 15s |
| **Total** | **21-95s** | **195s** |

**Recommendation:** Set `timeout_seconds` to at least 200 (3+ minutes) to be safe.

---

## Troubleshooting

### Timeout Error
**Symptom:** `SCENARIO_CREATION_TIMEOUT` or `SCENARIO_RUN_TIMEOUT`
**Fix:** Increase `timeout_seconds` parameter (try 600)

### Template Not Found
**Symptom:** `TEMPLATE_NOT_FOUND` with 404
**Fix:** Verify template_id exists using Template Bedding Mock UI

### Scenario Run Failed
**Symptom:** `SCENARIO_RUN_FAILED` with core app error
**Fix:** Check core app logs, verify hotel_id and dates

### API Key Not Assigned to BR
**Symptom:** `"assigned_to_br": false` in response
**Fix:** Set `assign_api_key_to_br: true` in request

### Mocks Not Cleaned Up
**Symptom:** `"deleted": false` but `delete_mock_api_key: true`
**Fix:** Check backend logs for cleanup errors, manually cleanup if needed

---

## Support

For issues or questions:
1. Check request_id in logs for full execution trace
2. Include request_id when reporting bugs
3. Review error.message and error.code
4. Check core app logs if scenario run fails

---

**API Version:** v1  
**Status:** Production Ready  
**Last Updated:** 2026-07-28
