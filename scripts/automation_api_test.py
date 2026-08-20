#!/usr/bin/env python3
"""
Automation script to test run-template API with all scenarios
and collect results (label, search_id, package_id, status, etc.)
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
API_BASE_URL = "http://localhost:8000"
SCENARIO_FILE = Path(__file__).parent.parent / "scenario_id_labels.json"
OUTPUT_FILE = Path(__file__).parent.parent / "automation_results.json"

def call_automation_api(template_id, label):
    """Call the run-template API with appropriate parameters"""

    # Determine assign_api_key_to_br based on label
    has_without_markup = "Without Markup" in label
    assign_to_br = not has_without_markup  # False if "Without Markup", True otherwise

    url = f"{API_BASE_URL}/api/v1/run-template/{template_id}"
    payload = {
        "environment": "dev",
        "delete_mock_api_key": False,  # Keep scenarios for inspection
        "assign_api_key_to_br": assign_to_br
    }

    try:
        # Use curl to make the request
        cmd = [
            "curl",
            "-s",
            "-X", "POST",
            url,
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        api_response = json.loads(result.stdout)

        return {
            "label": label,
            "template_id": template_id,
            "assign_api_key_to_br": assign_to_br,
            "has_without_markup": has_without_markup,
            "status": api_response.get("status"),
            "search_id": api_response.get("search_id"),
            "package_id": api_response.get("package_id"),
            "scenario_id": api_response.get("scenario_id"),
            "api_key": api_response.get("api_key"),
            "contract_id": api_response.get("contract_id"),
            "check_in": api_response.get("check_in"),
            "check_out": api_response.get("check_out"),
            "deleted": api_response.get("deleted"),
            "error": api_response.get("error"),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "label": label,
            "template_id": template_id,
            "assign_api_key_to_br": assign_to_br,
            "has_without_markup": has_without_markup,
            "status": "ERROR",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def main():
    """Main automation function"""

    # Load scenario IDs and labels
    print(f"📂 Reading scenarios from: {SCENARIO_FILE}")
    with open(SCENARIO_FILE, 'r') as f:
        scenarios = json.load(f)

    print(f"📊 Found {len(scenarios)} scenarios to test")
    print(f"🚀 Starting API calls...\n")

    results = []

    for i, scenario in enumerate(scenarios, 1):
        template_id = scenario["id"]
        label = scenario["label"]

        print(f"[{i}/{len(scenarios)}] Testing: {label[:60]}...")

        result = call_automation_api(template_id, label)
        results.append(result)

        status_icon = "✅" if result["status"] == "COMPLETED" else "❌"
        print(f"  {status_icon} {result['status']} - search_id: {result.get('search_id', 'N/A')[:12] if result.get('search_id') else 'N/A'}...")

    # Save results
    print(f"\n💾 Saving results to: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    # Print summary
    completed = sum(1 for r in results if r["status"] == "COMPLETED")
    failed = sum(1 for r in results if r["status"] in ["FAILED", "ERROR"])

    print(f"\n📈 Summary:")
    print(f"  ✅ Completed: {completed}/{len(results)}")
    print(f"  ❌ Failed: {failed}/{len(results)}")
    print(f"  📁 Results saved to: {OUTPUT_FILE}")

    # Show first few results
    print(f"\n📋 First 3 results:")
    for result in results[:3]:
        print(f"  • {result['label'][:50]}")
        print(f"    Status: {result['status']}, Search ID: {result.get('search_id', 'N/A')[:12] if result.get('search_id') else 'N/A'}")

if __name__ == "__main__":
    main()
