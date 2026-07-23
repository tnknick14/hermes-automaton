#!/usr/bin/env python3
"""
Work Modules for Hermes Agent
Each module is a self-contained unit of work that can be executed autonomously.
"""

import json
import os
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# ── Base Module ────────────────────────────────────────────────

class WorkModule:
    """Base class for all work modules"""
    
    def __init__(self, agent):
        self.agent = agent
        self.api_key = agent.api_key
        self.api_base = agent.api_base
        self.model = agent.model
        
    def think(self, system_prompt: str, user_message: str, max_tokens: int = 2000) -> Optional[str]:
        """Call LongCat API for reasoning"""
        try:
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
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0)
                cost = (tokens / 1000) * 0.002
                self.agent.record_expense("inference", f"{self.__class__.__name__} ({tokens} tokens)", cost)
                return content if content else None
            self.agent.log("error", f"API {resp.status_code}: {resp.text[:200]}")
            return None
        except Exception as e:
            self.agent.log("error", f"Inference failed: {e}")
            return None


# ── GitHub Bounty Analyzer ─────────────────────────────────────

class BountyAnalyzer(WorkModule):
    """Analyzes GitHub bounties and decides which are worth pursuing"""
    
    def scan(self) -> List[dict]:
        """Scan GitHub for bounty issues"""
        opportunities = []
        queries = self.agent.config.get("github", {}).get("search_queries", [
            "label:bounty state:open",
            "label:\"good first issue\" state:open",
            "label:\"help wanted\" state:open"
        ])
        
        for query in queries:
            try:
                url = "https://api.github.com/search/issues"
                params = {
                    "q": query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 10
                }
                headers = {}
                github_token = os.environ.get("GITHUB_TOKEN", "")
                if github_token:
                    headers["Authorization"] = f"token {github_token}"
                    
                resp = requests.get(url, params=params, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("items", []):
                        opportunities.append({
                            "type": "github_bounty",
                            "title": item["title"],
                            "url": item["html_url"],
                            "repo": item["repository_url"].split("/")[-1],
                            "created": item["created_at"],
                            "labels": [l["name"] for l in item.get("labels", [])],
                            "body": (item.get("body") or "")[:500]
                        })
                time.sleep(1)  # Rate limit
            except Exception as e:
                self.agent.log("error", f"GitHub scan failed for '{query}': {e}")
                
        return opportunities
    
    def analyze(self, opportunity: dict) -> dict:
        """Analyze a single opportunity and return a score + reasoning"""
        system_prompt = """You are a pragmatic freelance developer evaluating GitHub issues for paid work.
Score each opportunity from 0-100 based on:
- Clarity of requirements (can I understand what to do?)
- Scope size (can I complete this in under 2 hours?)
- Payment likelihood (is there actually a bounty?)
- Competition (how many others might do this faster?)
- Technical fit (can I actually do this?)

Return JSON: {"score": N, "reasoning": "...", "estimated_hours": N, "should_pursue": true/false}"""

        user_message = f"""Evaluate this GitHub opportunity:

Title: {opportunity['title']}
Repo: {opportunity['repo']}
Labels: {', '.join(opportunity['labels'])}
URL: {opportunity['url']}

Description:
{opportunity['body']}

Be honest. If it's vague, low-paying, or too complex, say so."""

        response = self.think(system_prompt, user_message, max_tokens=500)
        if response:
            try:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    result["raw_response"] = response
                    return result
            except json.JSONDecodeError:
                pass
            return {"score": 0, "reasoning": response, "estimated_hours": 0, "should_pursue": False}
        return {"score": 0, "reasoning": "Analysis failed", "estimated_hours": 0, "should_pursue": False}
    
    def run(self) -> List[dict]:
        """Full scan + analyze pipeline"""
        self.agent.log("work", "Scanning GitHub for bounties...")
        opportunities = self.scan()
        self.agent.log("work", f"Found {len(opportunities)} opportunities")
        
        analyzed = []
        for opp in opportunities[:5]:  # Analyze top 5
            result = self.analyze(opp)
            opp["analysis"] = result
            analyzed.append(opp)
            self.agent.log("work", f"  {opp['title'][:50]}... → Score: {result.get('score', 'N/A')}")
            
        # Sort by score
        analyzed.sort(key=lambda x: x.get("analysis", {}).get("score", 0), reverse=True)
        return analyzed


# ── Proposal Generator ─────────────────────────────────────────

class ProposalGenerator(WorkModule):
    """Generates proposals for opportunities"""
    
    def generate(self, opportunity: dict) -> Optional[str]:
        """Generate a proposal for a GitHub bounty"""
        system_prompt = """You are a professional freelance developer writing a concise proposal for a GitHub bounty.
Your proposal should:
1. Show you understand the problem
2. Briefly explain your approach
3. State your relevant experience
4. Give a realistic timeline
5. Ask one clarifying question if needed

Keep it under 200 words. Be direct, not salesy."""

        user_message = f"""Write a proposal for this GitHub issue:

Title: {opportunity['title']}
Repo: {opportunity['repo']}
URL: {opportunity['url']}

Description:
{opportunity.get('body', 'No description')[:500]}

Score: {opportunity.get('analysis', {}).get('score', 'N/A')}
Estimated hours: {opportunity.get('analysis', {}).get('estimated_hours', 'N/A')}"""

        return self.think(system_prompt, user_message, max_tokens=300)


# ── Service Offer Creator ──────────────────────────────────────

class OfferCreator(WorkModule):
    """Creates service offers based on capabilities"""
    
    def create_offers(self) -> List[dict]:
        """Generate service offers based on available tools"""
        system_prompt = """You are a business strategist creating service offers for a solo AI-assisted developer.
Based on available skills (Python, web dev, APIs, trading bots, data analysis), create 3 concrete service offers.

Each offer should have:
- title: Short, clear service name
- description: What you deliver
- price: Specific price in USD
- delivery_time: How long it takes
- target_customer: Who needs this

Return JSON array: [{"title": "...", "description": "...", "price": 49, "delivery_time": "2 days", "target_customer": "..."}]"""

        response = self.think(system_prompt, "Generate 3 service offers.", max_tokens=500)
        if response:
            try:
                import re
                json_match = re.search(r'\[.*\]', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return []


# ── Market Researcher ──────────────────────────────────────────

class MarketResearcher(WorkModule):
    """Researches market opportunities"""
    
    def research(self, query: str) -> Optional[str]:
        """Research a market or opportunity"""
        system_prompt = """You are a market researcher. Provide concise, actionable insights.
Focus on:
- Current demand level
- Competition analysis
- Pricing benchmarks
- Entry barriers
- Realistic revenue potential

Be specific and honest. No fluff."""

        return self.think(system_prompt, query, max_tokens=800)


# ── Delivery Tracker ───────────────────────────────────────────

class DeliveryTracker(WorkModule):
    """Tracks delivery of completed work"""
    
    def create_delivery_plan(self, job: dict) -> dict:
        """Create a delivery plan for a job"""
        system_prompt = """You are a project manager creating a delivery plan.
Break the work into concrete steps with time estimates.
Return JSON: {"steps": [{"task": "...", "hours": N}], "total_hours": N, "risks": ["..."]}"""

        response = self.think(system_prompt, f"Create delivery plan for: {job['title']}\nDescription: {job.get('description', '')}", max_tokens=500)
        if response:
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {"steps": [], "total_hours": 0, "risks": []}


# ── Self-Improver ──────────────────────────────────────────────

class SelfImprover(WorkModule):
    """Reviews past performance and suggests improvements"""
    
    def review_performance(self) -> dict:
        """Review recent performance and suggest improvements"""
        # Load recent transactions
        recent_tx = self.agent.ledger.get("transactions", [])[-20:]
        recent_tasks = self.agent.tasks.get("completed", [])[-10:]
        recent_failed = self.agent.tasks.get("failed", [])[-10:]
        
        system_prompt = """You are a business coach reviewing an autonomous agent's performance.
Analyze the data and provide 3 concrete, actionable improvements.
Be specific: change X to Y, not "try harder."

Return JSON: {"improvements": [{"area": "...", "action": "...", "expected_impact": "..."}]}"""

        user_message = f"""Recent transactions: {json.dumps(recent_tx, indent=2)[:1000]}

Completed tasks: {len(recent_tasks)}
Failed tasks: {len(recent_failed)}

Total earned: ${self.agent.ledger.get('total_earned', 0)}
Total spent: ${self.agent.ledger.get('total_spent', 0)}"""

        response = self.think(system_prompt, user_message, max_tokens=500)
        if response:
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {"improvements": []}
