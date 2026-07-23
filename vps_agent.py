#!/usr/bin/env python3
"""
Hermes Autonomous Hustle Engine
A permanent, self-contained agent for VPS deployment.
No Conway. No wallet-gated credits. Direct API calls only.
"""

import json
import os
import time
import subprocess
import requests
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add work modules to path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from work_modules import BountyAnalyzer, ProposalGenerator, OfferCreator, MarketResearcher, DeliveryTracker, SelfImprover
from revenue_scanner import UnifiedRevenueScanner
from execution_engine import ExecutionEngine

# ── Configuration ──────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yaml"
LEDGER_PATH = Path(__file__).parent / "ledger.json"
CRM_PATH = Path(__file__).parent / "crm.json"
TASKS_PATH = Path(__file__).parent / "tasks.json"
LOG_PATH = Path(__file__).parent / "logs"

class HermesAgent:
    def __init__(self):
        self.load_config()
        self.load_state()
        self.ensure_dirs()
        
    def load_config(self):
        with open(CONFIG_PATH) as f:
            self.config = yaml.safe_load(f)
        self.api_key = os.environ.get("LONGCAT_API_KEY", self.config["api"]["key"])
        self.api_base = self.config["api"]["base_url"]
        self.model = self.config["api"]["model"]
        self.wallet_address = self.config["wallet"]["address"]
        self.rpc_url = self.config["wallet"]["rpc_url"]
        self.max_daily_spend = self.config["limits"]["max_daily_spend_usd"]
        self.max_single_transaction = self.config["limits"]["max_single_transaction_usd"]
        
    def load_state(self):
        self.ledger = self.load_json(LEDGER_PATH, {
            "balance_usd": 0,
            "total_earned": 0,
            "total_spent": 0,
            "transactions": []
        })
        self.crm = self.load_json(CRM_PATH, {
            "leads": [],
            "customers": [],
            "active_jobs": [],
            "completed_jobs": []
        })
        self.tasks = self.load_json(TASKS_PATH, {
            "queue": [],
            "active": [],
            "completed": [],
            "failed": []
        })
        
    def load_json(self, path: Path, default: dict) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return default
        
    def save_state(self):
        with open(LEDGER_PATH, 'w') as f:
            json.dump(self.ledger, f, indent=2)
        with open(CRM_PATH, 'w') as f:
            json.dump(self.crm, f, indent=2)
        with open(TASKS_PATH, 'w') as f:
            json.dump(self.tasks, f, indent=2)
            
    def ensure_dirs(self):
        LOG_PATH.mkdir(exist_ok=True)
        
    def log(self, category: str, message: str, data: dict = None):
        timestamp = datetime.now().isoformat()
        entry = {
            "timestamp": timestamp,
            "category": category,
            "message": message
        }
        if data:
            entry["data"] = data
        log_file = LOG_PATH / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + "\n")
        print(f"[{timestamp}] {category}: {message}")
        
    # ── Financial Operations ─────────────────────────────────────
    
    def get_wallet_balance(self) -> float:
        """Check USDC balance on Base"""
        try:
            # USDC contract on Base
            usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
            # balanceOf selector + address padded
            data = "0x70a08231" + "0" * 24 + self.wallet_address[2:]
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": usdc, "data": data}, "latest"],
                "id": 1
            }
            resp = requests.post(self.rpc_url, json=payload, timeout=10)
            result = resp.json()["result"]
            balance = int(result, 16) / 1e6
            return balance
        except Exception as e:
            self.log("error", f"Balance check failed: {e}")
            return self.ledger.get("last_known_balance", 0)
            
    def can_spend(self, amount_usd: float) -> bool:
        """Check if we can afford an expense"""
        if amount_usd > self.max_single_transaction:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        today_spent = sum(
            t["amount"] for t in self.ledger["transactions"]
            if t["type"] == "expense" and t["timestamp"].startswith(today)
        )
        return (today_spent + amount_usd) <= self.max_daily_spend
        
    def record_expense(self, category: str, description: str, amount_usd: float):
        """Record an expense"""
        if not self.can_spend(amount_usd):
            self.log("warning", f"Cannot spend ${amount_usd}: limit exceeded")
            return False
        self.ledger["transactions"].append({
            "type": "expense",
            "category": category,
            "description": description,
            "amount": amount_usd,
            "timestamp": datetime.now().isoformat()
        })
        self.ledger["total_spent"] += amount_usd
        self.save_state()
        self.log("finance", f"Expense: ${amount_usd} - {category}: {description}")
        return True
        
    def record_revenue(self, source: str, description: str, amount_usd: float):
        """Record revenue"""
        self.ledger["transactions"].append({
            "type": "revenue",
            "source": source,
            "description": description,
            "amount": amount_usd,
            "timestamp": datetime.now().isoformat()
        })
        self.ledger["total_earned"] += amount_usd
        self.save_state()
        self.log("finance", f"Revenue: ${amount_usd} - {source}: {description}")
        
    # ── Inference ────────────────────────────────────────────────
    
    def think(self, system_prompt: str, user_message: str, max_tokens: int = 2000) -> Optional[str]:
        """Call LongCat API for reasoning"""
        try:
            start = time.time()
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "max_tokens": max_tokens
                },
                timeout=60
            )
            elapsed = time.time() - start
            if resp.status_code == 200:
                data = resp.json()
                # Handle both content and reasoning_content (LongCat-2.0 returns reasoning_content)
                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0)
                cost = (tokens / 1000) * 0.002
                self.record_expense("inference", f"API call ({tokens} tokens)", cost)
                self.log("inference", f"Thought in {elapsed:.1f}s, {tokens} tokens, ${cost:.4f}")
                return content if content else None
            else:
                self.log("error", f"API error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            self.log("error", f"Inference failed: {e}")
            return None
            
    # ── Daily Autonomous Loop ────────────────────────────────────
    
    def daily_loop(self):
        """Execute the daily autonomous loop"""
        self.log("system", "=== DAILY LOOP START ===")
        
        # 1. Check system health
        self.check_health()
        
        # 2. Check funds
        balance = self.get_wallet_balance()
        self.ledger["last_known_balance"] = balance
        self.save_state()
        self.log("finance", f"Wallet balance: ${balance:.2f}")
        
        # 3. Review active tasks
        self.review_tasks()
        

        
        # 4-5. Multi-source revenue scan + execute work modules
        self.run_revenue_scan()
        
        # 6. Self-improvement review (every 7 days)
        if datetime.now().weekday() == 0:  # Monday
            self.run_self_improvement()
        
        # 7. End of cycle report
        self.end_of_cycle_report()
        
        self.log("system", "=== DAILY LOOP END ===")
        
    def run_revenue_scan(self):
        """Run unified multi-source revenue scanner + execute top opportunities"""
        # 1. Scan all sources
        scanner = UnifiedRevenueScanner(self)
        analyzed = scanner.run_full_scan()
        
        # 2. Execute top opportunities (score >= 60)
        engine = ExecutionEngine(self)
        engine.execute_top_opportunities(analyzed, max_to_execute=3)
        
        # 3. Execute work modules on remaining opportunities
        self.execute_work_modules(analyzed)
        
    def execute_work_modules(self, opportunities: List[dict]):
        """Execute all active work modules"""
        
        # Module 1: GitHub Bounty Analyzer
        if self.config.get("modules", {}).get("bounty_analyzer", True):
            analyzer = BountyAnalyzer(self)
            analyzed = analyzer.run()
            
            # Save high-scoring opportunities
            for opp in analyzed:
                if opp.get("analysis", {}).get("score", 0) >= 60:
                    self.tasks["queue"].append({
                        "type": "github_bounty",
                        "status": "queued",
                        "title": opp["title"],
                        "url": opp["url"],
                        "score": opp["analysis"]["score"],
                        "created": datetime.now().isoformat()
                    })
                    self.log("work", f"Queued: {opp['title'][:50]} (score: {opp['analysis']['score']})")
        
        # Module 2: Offer Creator
        if self.config.get("modules", {}).get("offer_creator", True):
            creator = OfferCreator(self)
            offers = creator.create_offers()
            if offers:
                self.log("work", f"Created {len(offers)} service offers")
                # Save offers to CRM
                for offer in offers:
                    self.crm.setdefault("offers", []).append({
                        **offer,
                        "created": datetime.now().isoformat(),
                        "status": "active"
                    })
        
        # Module 3: Proposal Generator for top opportunities
        if self.tasks["queue"] and self.config.get("modules", {}).get("proposal_generator", True):
            # Process top queued item
            top_task = self.tasks["queue"][0]
            if top_task["type"] == "github_bounty":
                generator = ProposalGenerator(self)
                proposal = generator.generate(top_task)
                if proposal:
                    top_task["proposal"] = proposal
                    top_task["status"] = "proposal_ready"
                    self.log("work", f"Generated proposal for: {top_task['title'][:50]}")
        
        self.save_state()
        
    def run_self_improvement(self):
        """Run weekly self-improvement review"""
        self.log("work", "Running self-improvement review...")
        improver = SelfImprover(self)
        results = improver.review_performance()
        if results.get("improvements"):
            for imp in results["improvements"]:
                self.log("improvement", f"{imp['area']}: {imp['action']}")
        
    def check_health(self):
        """Check system health"""
        # Check disk usage
        try:
            result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                usage = lines[1].split()[4].replace("%", "")
                if int(usage) > 85:
                    self.log("warning", f"Disk usage high: {usage}%")
        except Exception as e:
            self.log("error", f"Health check failed: {e}")
            
        # Check memory
        try:
            result = subprocess.run(["free", "-m"], capture_output=True, text=True)
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                mem_info = lines[1].split()
                total, used = int(mem_info[1]), int(mem_info[2])
                pct = (used / total) * 100
                if pct > 90:
                    self.log("warning", f"Memory usage high: {pct:.0f}%")
        except Exception as e:
            self.log("error", f"Memory check failed: {e}")
            
    def review_tasks(self):
        """Review and update task status"""
        # Remove stale tasks (>7 days in queue)
        cutoff = datetime.now() - timedelta(days=7)
        self.tasks["queue"] = [
            t for t in self.tasks["queue"]
            if datetime.fromisoformat(t["created"]) > cutoff
        ]
        
        # Retry failed tasks if retries left
        for task in self.tasks["failed"]:
            if task.get("retries", 0) < 3:
                task["retries"] += 1
                task["status"] = "queued"
                self.tasks["queue"].append(task)
        self.tasks["failed"] = [t for t in self.tasks["failed"] if t.get("retries", 0) >= 3]
        
        self.save_state()
        

        
            
    def end_of_cycle_report(self):
        """End of cycle report"""
        today = datetime.now().strftime("%Y-%m-%d")
        today_transactions = [
            t for t in self.ledger["transactions"]
            if t["timestamp"].startswith(today)
        ]
        earned = sum(t["amount"] for t in today_transactions if t["type"] == "revenue")
        spent = sum(t["amount"] for t in today_transactions if t["type"] == "expense")
        
        self.log("report", f"Today: +${earned:.2f} / -${spent:.2f} | Balance: ${self.ledger['last_known_balance']:.2f}")
        
    # ── Main Run Loop ────────────────────────────────────────────
    
    def run(self):
        """Main run loop - runs forever"""
        self.log("system", "Hermes Agent starting...")
        
        while True:
            try:
                self.daily_loop()
            except Exception as e:
                self.log("error", f"Cycle error: {e}")
                
            # Sleep for configured interval (default 1 hour)
            interval = self.config["limits"].get("loop_interval_seconds", 3600)
            self.log("system", f"Sleeping for {interval}s...")
            time.sleep(interval)


if __name__ == "__main__":
    agent = HermesAgent()
    agent.run()
