"""ConditionalPipeline — routing-aware sequential orchestrator.

Replaces the outer SequentialAgent so that phases are simply NOT CALLED
when they should be skipped.  This eliminates all skip-event noise:
there are no "[skipped: ...]" messages because the agents are never invoked.

Phase routing rules
-------------------
Phase 0  intent_gate         — always runs
Phase 1  analyst_team        — runs when analysis_intent=True AND NOT awaiting
Phase 1.5 master_selector    — runs when analysis_intent=True
Phase 2  masters_panel       — runs when analysis_intent=True AND masters selected AND NOT awaiting
                             (also writes consolidated_masters_report)
Phase 3  research_debate     — runs after masters_panel
Phase 4  research_manager    — runs after research_debate
Phase 4b trader              — runs after research_manager
Phase 5  risk_debate         — runs after trader
Phase 6  portfolio_manager   — runs after risk_debate

State key reads (from ctx.session.state, refreshed after each phase):
    analysis_intent: bool   — set by intent_gate
    awaiting_master_choice: bool — set/cleared by master_selector tool
    selected_masters: list  — set by master_selector tool
"""
import logging
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from typing_extensions import override

logger = logging.getLogger(__name__)

# Sub-agent name constants (must match the `name=` field on each agent object).
_INTENT_GATE = "intent_gate"
_ANALYST_TEAM = "analyst_team"
_MASTER_SELECTOR = "master_selector"
_MASTERS_PANEL = "masters_panel"
_RESEARCH_DEBATE = "research_debate"
_RESEARCH_MANAGER = "research_manager"
_TRADER = "trader"
_RISK_DEBATE = "risk_debate"
_PORTFOLIO_MANAGER = "portfolio_manager"


class ConditionalPipeline(BaseAgent):
    """Routes pipeline phases based on session state; produces zero skip events."""

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        reg = {a.name: a for a in self.sub_agents}
        state = ctx.session.state  # live reference — updated after each phase

        # ------------------------------------------------------------------
        # Phase 0: intent gate — always runs
        # ------------------------------------------------------------------
        if agent := reg.get(_INTENT_GATE):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found in sub_agents", _INTENT_GATE)
            return

        if not state.get("analysis_intent"):
            logger.info("ConditionalPipeline: analysis_intent=False — stopping after intent_gate.")
            return

        # ------------------------------------------------------------------
        # Phase 1: analyst team — skip when awaiting master choice
        # ------------------------------------------------------------------
        if not state.get("awaiting_master_choice"):
            if agent := reg.get(_ANALYST_TEAM):
                async for event in agent.run_async(ctx):
                    yield event

        # ------------------------------------------------------------------
        # Phase 1.5: master selector — runs on every analysis turn
        # ------------------------------------------------------------------
        if agent := reg.get(_MASTER_SELECTOR):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found", _MASTER_SELECTOR)
            return

        # ------------------------------------------------------------------
        # Phase 2: masters panel (includes deterministic consolidation)
        # ------------------------------------------------------------------
        if state.get("awaiting_master_choice") or not state.get("selected_masters"):
            logger.info("ConditionalPipeline: awaiting master choice or no selection — halting.")
            return

        if agent := reg.get(_MASTERS_PANEL):
            async for event in agent.run_async(ctx):
                yield event

        # ------------------------------------------------------------------
        # Phase 3-6: downstream decision pipeline
        # ------------------------------------------------------------------
        if agent := reg.get(_RESEARCH_DEBATE):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found", _RESEARCH_DEBATE)
            return

        if agent := reg.get(_RESEARCH_MANAGER):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found", _RESEARCH_MANAGER)
            return

        if agent := reg.get(_TRADER):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found", _TRADER)
            return

        if agent := reg.get(_RISK_DEBATE):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found", _RISK_DEBATE)
            return

        if agent := reg.get(_PORTFOLIO_MANAGER):
            async for event in agent.run_async(ctx):
                yield event
        else:
            logger.error("ConditionalPipeline: %r not found", _PORTFOLIO_MANAGER)
            return
