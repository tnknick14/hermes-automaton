#!/usr/bin/env python3
"""
Opportunity Execution Engine
Acts on scored opportunities automatically.
Submits proposals, applies for work, posts content, and contacts clients.
"""

import json
import os
import time
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path


# ── Base Executor ──────────────────────────────────────────────

class OpportunityExecutor:
    """Base class for opportunity execution"""
    
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


# ── GitHub Bounty Executor ────────────────────────────────────

class GitHubExecutor(OpportunityExecutor):
    """Submits proposals and claims GitHub bounties"""
    
    def execute(self, opportunity: dict) -> bool:
        """Execute action on a GitHub bounty"""
        self.agent.log("work", f"Acting on GitHub bounty: {opportunity['title'][:50]}")
        
        # Step 1: Get issue details
        issue_details = self.get_issue_details(opportunity["url"])
        if not issue_details:
            return False
            
        # Step 2: Generate proposal/cover letter
        proposal = self.generate_proposal(opportunity, issue_details)
        if not proposal:
            return False
            
        # Step 3: Post comment on issue (if GitHub token has push access)
        posted = self.post_proposal(opportunity["url"], proposal)
        
        # Step 4: Record action
        self.record_action("github_bounty", opportunity, proposal, posted)
        
        return posted
    
    def get_issue_details(self, url: str) -> Optional[dict]:
        """Get full issue details from GitHub API"""
        try:
            headers = {}
            github_token = os.environ.get("GITHUB_TOKEN", "")
            if github_token:
                headers["Authorization"] = f"token {github_token}"
                
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            self.agent.log("error", f"Failed to get issue details: {e}")
            return None
    
    def generate_proposal(self, opportunity: dict, details: dict) -> Optional[str]:
        """Generate a proposal for a GitHub bounty"""
        system_prompt = """You are a freelance developer responding to a GitHub bounty issue.
Write a SHORT, direct comment (under 150 words) that:
1. Shows you understand the issue briefly
2. States you can fix it
3. Asks one clarifying question if needed
4. Indicates you'll submit a PR

Do NOT use emoji, marketing language, or excessive politeness.
Be direct and technical."""

        user_message = f"""GitHub Issue: {opportunity['title']}
Repository: {opportunity.get('repo', 'unknown')}

Description:
{(details.get('body') or '')[:1000]}

Write a comment proposing your solution."""

        return self.think(system_prompt, user_message, max_tokens=300)
    
    def post_proposal(self, issue_url: str, proposal: str) -> bool:
        """Post proposal as comment on GitHub issue"""
        try:
            headers = {}
            github_token = os.environ.get("GITHUB_TOKEN", "")
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            else:
                self.agent.log("warning", "No GitHub token — cannot post proposal")
                return False
                
            # Post comment
            comments_url = issue_url.replace("github.com", "api.github.com/repos") + "/comments"
            # Fix URL: issue URL is /repos/OWNER/REPO/issues/NUMBER
            comments_url = issue_url + "/comments"
            comments_url = comments_url.replace("github.com", "api.github.com/repos")
            
            resp = requests.post(
                comments_url,
                headers={**headers, "Accept": "application/vnd.github.v3+json"},
                json={"body": proposal},
                timeout=15
            )
            
            if resp.status_code == 201:
                self.agent.log("work", "Proposal posted successfully")
                return True
            else:
                self.agent.log("error", f"Failed to post proposal: {resp.status_code} {resp.text[:200]}")
                return False
        except Exception as e:
            self.agent.log("error", f"Failed to post proposal: {e}")
            return False
    
    def record_action(self, action_type: str, opportunity: dict, content: str, success: bool):
        """Record the action taken"""
        self.agent.ledger["transactions"].append({
            "type": "action",
            "category": action_type,
            "title": opportunity["title"][:100],
            "url": opportunity.get("url", ""),
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        self.agent.save_state()


# ── Freelance Application Executor ────────────────────────────

class FreelanceExecutor(OpportunityExecutor):
    """Applies to freelance jobs on various platforms"""
    
    def execute(self, opportunity: dict) -> bool:
        """Execute action on a freelance job"""
        self.agent.log("work", f"Acting on freelance job: {opportunity['title'][:50]}")
        
        platform = opportunity.get("source", "unknown")
        
        if platform == "upwork":
            return self.apply_upwork(opportunity)
        elif platform == "reddit":
            return self.apply_reddit(opportunity)
        else:
            return self.apply_generic(opportunity)
    
    def apply_upwork(self, opportunity: dict) -> bool:
        """Generate Upwork proposal"""
        system_prompt = """You are writing a freelance proposal for Upwork.
Keep it under 150 words. Be specific about:
- What you'll do
- Your relevant experience
- Timeline
- One question to show you read the post

Do NOT use templates or generic language. Address the specific problem."""

        user_message = f"""Job: {opportunity['title']}
Description: {opportunity.get('description', '')[:500]}
URL: {opportunity.get('url')}"""

        proposal = self.think(system_prompt, user_message, max_tokens=250)
        if proposal:
            self.record_action("upwork_proposal", opportunity, proposal, True)
            return True
        return False
    
    def apply_reddit(self, opportunity: dict) -> bool:
        """Generate Reddit DM/comment response"""
        system_prompt = """You are responding to a 'for hire' post on Reddit.
Write a SHORT, direct message (under 100 words):
- Show you understand what they need
- State your relevant skill
- Ask for more details
- NO marketing speak, NO emoji overload"""

        user_message = f"""Reddit post: {opportunity['title']}
Subreddit: {opportunity.get('subreddit', '')}
Content: {opportunity.get('selftext', '')[:500]}"""

        response = self.think(system_prompt, user_message, max_tokens=200)
        if response:
            self.record_action("reddit_response", opportunity, response, True)
            return True
        return False
    
    def apply_generic(self, opportunity: dict) -> bool:
        """Generate generic application"""
        system_prompt = """Write a short, professional proposal (under 150 words) for a freelance job.
Be direct, show understanding of the problem, state your approach."""

        user_message = f"""Job: {opportunity['title']}
Description: {opportunity.get('description', opportunity.get('selftext', ''))[:500]}"""

        proposal = self.think(system_prompt, user_message, max_tokens=250)
        if proposal:
            self.record_action("generic_application", opportunity, proposal, True)
            return True
        return False
    
    def record_action(self, action_type: str, opportunity: dict, content: str, success: bool):
        """Record the action taken"""
        self.agent.ledger["transactions"].append({
            "type": "action",
            "category": action_type,
            "title": opportunity["title"][:100],
            "url": opportunity.get("url", ""),
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        self.agent.save_state()


# ── Content Creation Executor ─────────────────────────────────

class ContentExecutor(OpportunityExecutor):
    """Creates content for revenue platforms"""
    
    def execute(self, opportunity: dict) -> bool:
        """Create content for a trending topic"""
        self.agent.log("work", f"Creating content for: {opportunity.get('tag', 'unknown topic')}")
        
        # Generate article
        article = self.generate_article(opportunity)
        if not article:
            return False
        
        # Save article to workspace
        saved = self.save_article(opportunity, article)
        
        # Record action
        self.record_action("content_created", opportunity, article[:200], saved)
        
        return saved
    
    def generate_article(self, opportunity: dict) -> Optional[str]:
        """Generate a technical article"""
        system_prompt = """Write a short technical article (300-500 words) for dev.to.
The article should be useful, practical, and demonstrate expertise.
Include code examples where relevant.
Title should be clear and specific."""

        tag = opportunity.get('tag', 'python')
        user_message = f"""Write an article about: {tag}
Target audience: developers
Format: markdown with code examples"""

        return self.think(system_prompt, user_message, max_tokens=800)
    
    def save_article(self, opportunity: dict, article: str) -> bool:
        """Save article to workspace"""
        try:
            articles_dir = Path(self.agent.config.get("workspace", ".")) / "content"
            articles_dir.mkdir(exist_ok=True)
            
            tag = opportunity.get('tag', 'article')
            filename = f"{tag}-{datetime.now().strftime('%Y%m%d')}.md"
            filepath = articles_dir / filename
            
            with open(filepath, 'w') as f:
                f.write(article)
            
            self.agent.log("work", f"Article saved: {filepath}")
            return True
        except Exception as e:
            self.agent.log("error", f"Failed to save article: {e}")
            return False
    
    def record_action(self, action_type: str, opportunity: dict, content: str, success: bool):
        """Record the action taken"""
        self.agent.ledger["transactions"].append({
            "type": "action",
            "category": action_type,
            "title": f"Content: {opportunity.get('tag', 'article')}",
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        self.agent.save_state()


# ── Outreach Executor ─────────────────────────────────────────

class OutreachExecutor(OpportunityExecutor):
    """Sends outreach messages to potential clients"""
    
    def execute(self, opportunity: dict) -> bool:
        """Send outreach for a qualified lead"""
        self.agent.log("work", f"Preparing outreach for: {opportunity['title'][:50]}")
        
        # Generate outreach message
        message = self.generate_outreach(opportunity)
        if not message:
            return False
        
        # Save to outreach queue (doesn't send automatically — needs approval for external comms)
        self.save_to_outreach_queue(opportunity, message)
        
        return True
    
    def generate_outreach(self, opportunity: dict) -> Optional[str]:
        """Generate a personalized outreach message"""
        system_prompt = """Write a SHORT, direct outreach message (under 100 words) to a potential client.
- Reference their specific problem
- State how you can help
- Ask one question
- NO marketing speak, NO templates"""

        user_message = f"""Opportunity: {opportunity['title']}
Description: {opportunity.get('description', opportunity.get('selftext', ''))[:300]}"""

        return self.think(system_prompt, user_message, max_tokens=200)
    
    def save_to_outreach_queue(self, opportunity: dict, message: str):
        """Save to outreach queue for approval"""
        outreach_queue = Path(self.agent.config.get("workspace", ".")) / "outreach_queue.json"
        
        queue = []
        if outreach_queue.exists():
            with open(outreach_queue) as f:
                queue = json.load(f)
        
        queue.append({
            "opportunity": opportunity["title"][:100],
            "url": opportunity.get("url", ""),
            "message": message,
            "created": datetime.now().isoformat(),
            "status": "pending_approval"
        })
        
        with open(outreach_queue, 'w') as f:
            json.dump(queue, f, indent=2)
        
        self.agent.log("work", f"Outreach saved to queue: {opportunity['title'][:50]}")
        
        self.agent.ledger["transactions"].append({
            "type": "action",
            "category": "outreach_queued",
            "title": opportunity["title"][:100],
            "url": opportunity.get("url", ""),
            "success": True,
            "timestamp": datetime.now().isoformat()
        })
        self.agent.save_state()


# ── Unified Execution Engine ─────────────────────────────────

class ExecutionEngine:
    """Master executor that routes opportunities to the right executor"""
    
    def __init__(self, agent):
        self.agent = agent
        self.executors = {
            "github": GitHubExecutor(agent),
            "freelance": FreelanceExecutor(agent),
            "content": ContentExecutor(agent),
            "outreach": OutreachExecutor(agent),
        }
    
    def execute_opportunity(self, opportunity: dict) -> bool:
        """Route and execute an opportunity"""
        source = opportunity.get("source", "unknown")
        opp_type = opportunity.get("type", "unknown")
        
        # Route to correct executor
        if source == "github":
            return self.executors["github"].execute(opportunity)
        elif source in ("upwork", "freelancer", "reddit"):
            return self.executors["freelance"].execute(opportunity)
        elif source == "devto":
            return self.executors["content"].execute(opportunity)
        else:
            # Default: outreach
            return self.executors["outreach"].execute(opportunity)
    
    def execute_top_opportunities(self, opportunities: List[dict], max_to_execute: int = 3):
        """Execute top N opportunities"""
        executed = 0
        for opp in opportunities[:max_to_execute]:
            if opp.get("analysis", {}).get("score", 0) >= 40:
                success = self.execute_opportunity(opp)
                if success:
                    executed += 1
                time.sleep(2)  # Rate limit
        
        self.agent.log("work", f"Executed {executed}/{min(max_to_execute, len(opportunities))} opportunities")
        return executed
