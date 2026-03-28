"""
OrionFlow 1000-Job Demo
Injects 250 parallel DAGs (= 1000 task nodes) into the running API server.
Run this WHILE your API and Workers are already up.
"""
import time
import random
import concurrent.futures

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

API = "http://localhost:8000"

def inject_dag(i):
    pri = random.randint(1, 100)
    requests.post(f"{API}/api/v1/workflows/dag", json={
        "dag": {
            "Extract": {"task_type": "extract", "priority": pri, "depends_on": []},
            "Transform_A": {"task_type": "transform", "priority": pri + 20, "depends_on": ["Extract"]},
            "Transform_B": {"task_type": "transform", "priority": pri + 10, "depends_on": ["Extract"]},
            "Load": {"task_type": "load", "priority": 50, "depends_on": ["Transform_A", "Transform_B"]}
        }
    })

if __name__ == "__main__":
    # Verify API is reachable
    try:
        requests.get(f"{API}/health", timeout=2)
    except:
        print("ERROR: API server is not running on port 8000!")
        print("Start it first: uvicorn orionflow.api.main:app --host 0.0.0.0 --port 8000")
        exit(1)

    print("=" * 60)
    print("  OrionFlow 1000-Job Distributed Demo")
    print("=" * 60)
    print()
    print("  Open http://localhost:8000/dashboard in your browser NOW!")
    print()
    
    input("  Press ENTER when your dashboard is open... ")
    print()
    
    print("  Injecting 250 DAG workflows (1000 total tasks)...")
    t0 = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        pool.map(inject_dag, range(250))
    
    print(f"  All 250 DAGs injected in {time.time() - t0:.1f}s!")
    print()
    print("  Monitoring progress (watch your dashboard!)...")
    print("-" * 60)
    
    while True:
        try:
            data = requests.get(f"{API}/api/v1/dashboard/data").json()
            c = data["counts"]
            workers = [w for w in data["workers"] if w["status"] != "OFFLINE"]
            
            bar_done = int((c["completed"] / 1000) * 30)
            bar = "█" * bar_done + "░" * (30 - bar_done)
            
            print(f"  [{bar}] {c['completed']:4d}/1000  |  Queued: {c['queued']:3d}  |  Running: {c['running']:2d}  |  Workers: {len(workers)}")
            
            if c["completed"] >= 1000:
                total = time.time() - t0
                print()
                print("=" * 60)
                print(f"  ✅ ALL 1000 TASKS COMPLETED!")
                print(f"  ⏱  Total time: {total:.1f}s")
                print(f"  🚀 Throughput: {1000/total:.1f} tasks/sec")
                print(f"  👷 Active workers: {len(workers)}")
                print(f"  ❌ Failed: {c['failed']}")
                print("=" * 60)
                break
        except Exception as e:
            pass
        time.sleep(1)
